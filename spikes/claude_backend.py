# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Claude Messages API wire format for the direct provider framework.

Authentication uses a Console API key as ``Authorization: Bearer``; the API documents
``x-api-key`` as a legacy fallback.  A key not scoped to one workspace also needs
``anthropic-workspace-id``, which ``auth_headers`` cannot supply, so such a key is
rejected by the API with HTTP 400: use a workspace-scoped key.

``json-output`` is deliberately never claimed.  The API has no schema-less JSON mode,
``output_config.format`` accepts only ``json_schema`` and every object must set
``additionalProperties`` to false, so no generic schema can express arbitrary JSON.
The per-model ``structured_outputs`` capability is therefore not sufficient while
``build_body`` receives no task schema.
"""
import re
from urllib.parse import quote

from spikes.direct_provider import (DirectBinding, DirectResponseError, ProviderSpec,
                                    register_direct)


API_VERSION = '2026-10-21'
MODELS_PAGE_LIMIT = 1000
_LABEL = re.compile(r'[a-z0-9][a-z0-9_.-]{0,63}')
_DATED_SNAPSHOT = re.compile(r'(.+)-[0-9]{8}')
_STOP_FAILURES = {
    'max_tokens': 'Claude response was truncated by max_tokens',
    'tool_use': 'Claude requested a tool, which this connector does not offer',
    'pause_turn': 'Claude paused the turn (pause_turn) without a complete answer',
    'stop_sequence': 'Claude stopped on an unexpected stop_sequence',
    'model_context_window_exceeded':
        'Claude response stopped at model_context_window_exceeded',
}
_THINKING_BLOCKS = {'thinking', 'redacted_thinking'}
_CACHE_USAGE = ('cache_creation_input_tokens', 'cache_read_input_tokens')
_KNOWN_EVENTS = {'message_start', 'content_block_start', 'content_block_delta',
                 'content_block_stop', 'message_delta', 'message_stop'}


def _label(value):
    """Provider-reported enum for an error message; free text could echo the request."""
    return value if isinstance(value, str) and _LABEL.fullmatch(value) else 'unknown'


def _auth_headers(secret):
    return {'Authorization': 'Bearer ' + secret, 'anthropic-version': API_VERSION}


def _build_body(prompt, binding, output_format, stream):
    if output_format != 'text':
        raise ValueError('Claude connector supports only text output')
    body = {'model': binding.model, 'max_tokens': binding.max_output_tokens,
            'messages': [{'role': 'user', 'content': prompt}]}
    if stream:
        body['stream'] = True
    return body


def _token_count(value):
    return type(value) is int and value >= 0


def _usage(value):
    if not isinstance(value, dict):
        return None
    input_tokens = value.get('input_tokens'); output_tokens = value.get('output_tokens')
    if not (_token_count(input_tokens) and _token_count(output_tokens)):
        return None
    for key in _CACHE_USAGE:
        # The API documents both counters as nullable, which means nothing was cached.
        cached = value.get(key)
        if cached is None:
            continue
        if not _token_count(cached):
            return None
        input_tokens += cached
    return {'input_tokens': input_tokens, 'output_tokens': output_tokens,
            'total_tokens': input_tokens + output_tokens}


def _check_stop_reason(value):
    reason = value.get('stop_reason')
    if reason == 'end_turn':
        return
    if reason == 'refusal':
        details = value.get('stop_details')
        category = details.get('category') if isinstance(details, dict) else None
        raise ValueError('Claude refused the request (category: ' + _label(category) + ')')
    if isinstance(reason, str) and reason in _STOP_FAILURES:
        raise ValueError(_STOP_FAILURES[reason])
    raise ValueError('Claude response has an unsupported stop_reason: ' + _label(reason))


def _text(content):
    if not isinstance(content, list):
        raise ValueError('Claude response content is invalid')
    parts = []
    for block in content:
        kind = block.get('type') if isinstance(block, dict) else None
        if kind in _THINKING_BLOCKS:
            continue
        if kind != 'text' or not isinstance(block.get('text'), str):
            raise ValueError('Claude response has an unsupported content block: '
                             + _label(kind))
        parts.append(block['text'])
    text = ''.join(parts)
    if not text:
        raise ValueError('Claude response has no text')
    return text


def _parse_response(value, binding):
    if not isinstance(value, dict) or value.get('type') != 'message' \
            or value.get('role') != 'assistant':
        raise ValueError('Claude response is not a message')
    if value.get('model') != binding.model:
        raise ValueError('Claude response model differs from the bound model')
    if not isinstance(value.get('id'), str) or not value['id']:
        raise ValueError('Claude response has no message ID')
    _check_stop_reason(value)
    response = {'id': value['id'], 'model': value['model'],
                'response': _text(value.get('content'))}
    usage = _usage(value.get('usage'))
    if usage is not None:
        response['usage'] = usage
    return response


def _merge_usage(state, usage):
    """Stream counters are cumulative; a null must not erase an earlier value."""
    if usage is None:
        return
    if not isinstance(usage, dict) or not isinstance(state['usage'], dict):
        state['usage'] = None
        return
    state['usage'].update({key: item for key, item in usage.items() if item is not None})


def _stream_state():
    return {'message': None, 'blocks': {}, 'open': set(), 'stopped': False,
            'stop_reason': None, 'stop_details': None, 'usage': {}}


def _block_index(event):
    index = event.get('index')
    if type(index) is not int or index < 0:
        raise ValueError('Claude stream has an invalid content block index')
    return index


def _start_block(state, event):
    index = _block_index(event); block = event.get('content_block')
    kind = block.get('type') if isinstance(block, dict) else None
    if not isinstance(kind, str) or index in state['blocks']:
        raise ValueError('Claude stream has an invalid content block')
    state['blocks'][index] = {'type': kind}; state['open'].add(index)
    if kind != 'text':
        return None
    initial = block.get('text', '')
    if not isinstance(initial, str):
        raise ValueError('Claude stream has an invalid content block')
    state['blocks'][index]['parts'] = [initial]
    return initial or None


def _block_delta(state, event):
    index = _block_index(event); delta = event.get('delta')
    if index not in state['open'] or not isinstance(delta, dict):
        raise ValueError('Claude stream delta targets no open content block')
    if delta.get('type') != 'text_delta':
        return None
    block = state['blocks'][index]; text = delta.get('text')
    if block['type'] != 'text' or not isinstance(text, str):
        raise ValueError('Claude stream has an invalid text delta')
    block['parts'].append(text)
    return text


def _stream_event(state, event):
    kind = event.get('type')
    if kind == 'error':
        details = event.get('error')
        raise DirectResponseError('Claude stream reported an error: ' + _label(
            details.get('type') if isinstance(details, dict) else None))
    if kind not in _KNOWN_EVENTS:
        return None  # ping and, per the versioning policy, future event types.
    if state['stopped']:
        raise ValueError('Claude stream continued after message_stop')
    if kind == 'message_start':
        message = event.get('message')
        if state['message'] is not None or not isinstance(message, dict):
            raise ValueError('Claude stream has an invalid message_start')
        state['message'] = message
        _merge_usage(state, message.get('usage'))
        return None
    if state['message'] is None:
        raise ValueError('Claude stream event arrived before message_start')
    if kind == 'content_block_start':
        return _start_block(state, event)
    if kind == 'content_block_delta':
        return _block_delta(state, event)
    if kind == 'content_block_stop':
        index = _block_index(event)
        if index not in state['open']:
            raise ValueError('Claude stream closed a content block that is not open')
        state['open'].remove(index)
    elif kind == 'message_delta':
        delta = event.get('delta')
        if not isinstance(delta, dict):
            raise ValueError('Claude stream has an invalid message_delta')
        for key in ('stop_reason', 'stop_details'):
            if delta.get(key) is not None:
                state[key] = delta[key]
        _merge_usage(state, event.get('usage'))
    else:
        if state['open']:
            raise ValueError('Claude stream stopped inside a content block')
        state['stopped'] = True
    return None


def _stream_final(state):
    if not state['stopped']:
        raise ConnectionError('Claude stream ended before message_stop')
    content = []
    for _, block in sorted(state['blocks'].items()):
        if block['type'] == 'text':
            content.append({'type': 'text', 'text': ''.join(block['parts'])})
        else:
            content.append({'type': block['type']})
    message = state['message']
    final = {'id': message.get('id'), 'type': message.get('type'),
             'role': message.get('role'), 'model': message.get('model'),
             'stop_reason': state['stop_reason'], 'stop_details': state['stop_details'],
             'content': content}
    if state['usage'] is not None:
        final['usage'] = state['usage']
    return final


def _models_path(cursor):
    path = '/v1/models?limit=' + str(MODELS_PAGE_LIMIT)
    return path if cursor is None else path + '&after_id=' + quote(cursor, safe='')


def _parse_models(value):
    if not isinstance(value, dict) or not isinstance(value.get('data'), list) \
            or type(value.get('has_more')) is not bool:
        raise ValueError('Invalid Claude model catalog')
    last_id = value.get('last_id')
    if last_id is not None and not isinstance(last_id, str):
        raise ValueError('Invalid Claude model catalog cursor')
    if value['has_more'] and not last_id:
        raise ValueError('Claude model catalog has more pages but no cursor')
    models = []
    for entry in value['data']:
        if not isinstance(entry, dict):
            raise ValueError('Invalid Claude model entry')
        if entry.get('type') != 'model' or entry.get('lifecycle') == 'retired':
            continue  # Inference naming a retired model fails, so it is no offer.
        if not isinstance(entry.get('id'), str):
            raise ValueError('Invalid Claude model entry')
        models.append(entry['id'])
    # A short alias moves between snapshots, so only its dated ID is a pinned offer.
    aliases = {match.group(1) for match in map(_DATED_SNAPSHOT.fullmatch, models) if match}
    return {'items': [{'model': model, 'capabilities': {
                'generate-text', 'text-output', 'streaming'}}
            for model in models if model not in aliases],
            'next_cursor': last_id if value['has_more'] else None}


SPEC = ProviderSpec(
    adapter_id='anthropic-messages', provider_id='anthropic', name='Claude',
    host='api.anthropic.com', endpoint='https://api.anthropic.com/v1/messages',
    protocol='anthropic-messages-v1', auth_headers=_auth_headers,
    generate_path=lambda model, stream: '/v1/messages', build_body=_build_body,
    parse_response=_parse_response, stream_state=_stream_state,
    stream_event=_stream_event, stream_final=_stream_final,
    models_path=_models_path, parse_models=_parse_models)


class ClaudeBinding(DirectBinding):
    spec = SPEC


register_direct(ClaudeBinding)
