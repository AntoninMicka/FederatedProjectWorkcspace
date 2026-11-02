# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""xAI Grok text over the official Responses API; wire format only, see ADR 0065.

Checked against https://docs.x.ai/openapi.json and the REST reference on 2026-11-02;
nothing here has run against the live API.

* ``store`` defaults to true (30 days), so every request sends ``store: false``.
* ``truncation`` is "Not supported" per ModelRequest and is not sent.
* ``text.format`` ``json_object`` is a documented ModelResponseFormat variant.
* ``/v1/language-models`` is used because ``/v1/models`` has no modalities; neither
  documents pagination.
* Aliases exist for requests, but the docs do not say which name ``model`` returns.
  Discovery therefore offers no alias, and a response must name the requested model
  exactly: a resolved name fails closed instead of passing as another model.
* Stream events come from the best-practices guide, not from the OpenAPI document,
  which has no event schemas.  ``response.failed``, ``error`` and ``sequence_number``
  are undocumented there and are handled defensively.
* ``total_tokens`` also counts reasoning, so usage is not checked as a sum.
"""
import re

from spikes.direct_provider import (DirectBinding, DirectResponseError, ProviderSpec,
                                    register_direct)
from spikes.metadata import require


_REASON = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}')
_USAGE = ('input_tokens', 'output_tokens', 'total_tokens')
_CAPABILITIES = frozenset({'generate-text', 'text-output', 'streaming', 'json-output'})


def _reason(value, key):
    # Only a short token is kept: provider messages could echo request content into
    # the stored run error.
    reason = value.get(key) if isinstance(value, dict) else None
    return (reason if isinstance(reason, str) and _REASON.fullmatch(reason)
            else 'unspecified')


def _not_completed(value):
    status = value.get('status')
    if status == 'incomplete':
        return 'Grok response is incomplete: ' + _reason(
            value.get('incomplete_details'), 'reason')
    if status == 'failed':
        return 'Grok response failed: ' + _reason(value.get('error'), 'code')
    return 'Grok response did not complete'


def _auth_headers(secret):
    return {'Authorization': 'Bearer ' + secret}


def _generate_path(model, stream):
    return '/v1/responses'


def _build_body(prompt, binding, output_format, stream):
    require(output_format in {'text', 'json'}, 'Unsupported Grok output format')
    body = {'model': binding.model, 'input': prompt, 'store': False,
            'max_output_tokens': binding.max_output_tokens, 'stream': stream}
    if output_format == 'json':
        body['text'] = {'format': {'type': 'json_object'}}
    return body


def _parse_response(value, binding):
    require(isinstance(value, dict), 'Invalid Grok response')
    require(value.get('status') == 'completed', _not_completed(value))
    require(isinstance(value.get('id'), str) and bool(value['id']),
            'Invalid Grok response ID')
    require(value.get('model') == binding.model,
            'Grok response did not come from the requested model')
    require(value.get('error') is None, 'Grok response reports an error')
    require(value.get('store', False) is False, 'Grok response was stored at the provider')
    output = value.get('output')
    require(isinstance(output, list) and bool(output)
            and all(isinstance(item, dict) and item.get('type') in {'reasoning', 'message'}
                    for item in output),
            'Grok response contains an unsupported output item')
    messages = [item for item in output if item['type'] == 'message']
    require(len(messages) == 1 and isinstance(messages[0].get('content'), list),
            'Grok response must contain exactly one output message')
    require(messages[0].get('status', 'completed') == 'completed'
            and messages[0].get('role', 'assistant') == 'assistant',
            'Grok output message is not a completed assistant message')
    content = messages[0]['content']
    require(bool(content) and all(isinstance(item, dict)
            and item.get('type') == 'output_text' and isinstance(item.get('text'), str)
            for item in content), 'Grok response contains unsupported message content')
    result = {'id': value['id'], 'model': value['model'],
              'response': ''.join(item['text'] for item in content)}
    usage = value.get('usage')
    if isinstance(usage, dict) and all(type(usage.get(key)) is int and usage[key] >= 0
                                       for key in _USAGE):
        result['usage'] = {key: usage[key] for key in _USAGE}
    return result


def _stream_state():
    return {'sequence': -1, 'completed': None}


def _stream_event(state, event):
    kind = event.get('type')
    require(isinstance(kind, str), 'Invalid Grok SSE event')
    sequence = event.get('sequence_number')
    if sequence is not None:
        require(type(sequence) is int and sequence > state['sequence'],
                'Invalid Grok SSE sequence')
        state['sequence'] = sequence
    if kind in {'response.failed', 'response.incomplete'}:
        response = event.get('response')
        raise DirectResponseError(_not_completed(response) if isinstance(response, dict)
                                  else 'Grok stream reported failure')
    if kind == 'error':
        raise DirectResponseError('Grok stream reported failure: ' + _reason(event, 'code'))
    require(state['completed'] is None, 'Grok stream continued after completion')
    if kind == 'response.output_text.delta':
        require(isinstance(event.get('delta'), str), 'Invalid Grok text delta')
        return event['delta']
    if kind == 'response.completed':
        require(isinstance(event.get('response'), dict), 'Invalid Grok completed event')
        state['completed'] = event['response']
    return None


def _stream_final(state):
    if state['completed'] is None:
        raise ConnectionError('Grok stream ended before completion')
    return state['completed']


def _models_path(cursor):
    require(cursor is None, 'Grok model discovery is not paginated')
    return '/v1/language-models'


def _strings(value):
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _parse_models(value):
    require(isinstance(value, dict) and isinstance(value.get('models'), list),
            'Invalid Grok model catalog')
    models = value['models']
    for model in models:
        require(isinstance(model, dict) and isinstance(model.get('id'), str)
                and _strings(model.get('aliases'))
                and _strings(model.get('input_modalities'))
                and _strings(model.get('output_modalities')),
                'Invalid Grok model entry')
    aliases = {alias for model in models for alias in model['aliases']}
    items = [{'model': model['id'], 'capabilities': set(_CAPABILITIES)} for model in models
             if model['output_modalities'] == ['text']
             and 'text' in model['input_modalities']
             and model['id'] != 'latest' and not model['id'].endswith('-latest')
             and model['id'] not in aliases]
    return {'items': items, 'next_cursor': None}


SPEC = ProviderSpec(
    adapter_id='xai-responses', provider_id='xai', name='Grok', host='api.x.ai',
    endpoint='https://api.x.ai/v1/responses', protocol='xai-responses-v1',
    auth_headers=_auth_headers, generate_path=_generate_path, build_body=_build_body,
    parse_response=_parse_response, stream_state=_stream_state,
    stream_event=_stream_event, stream_final=_stream_final,
    models_path=_models_path, parse_models=_parse_models)


class GrokBinding(DirectBinding):
    spec = SPEC


register_direct(GrokBinding)
