# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Gemini API (API key, not Vertex AI) text connector for the direct provider framework.

Uses ``generateContent``: the docs title it "Legacy" but state it "remains fully
supported" and publish no shutdown date, while the Interactions API stores interactions
by default and adds nothing to one stateless request.

Model rule (``_same_model``): the docs define ``modelVersion`` only as "the model version
used" and promise no format, so it is rejected only when definitely another model.  A
missing value is accepted.  A served name must equal the requested one or extend it with
version tokens only (digits, ``preview``, ``exp``).  A ``-latest`` alias is hot-swapped by
Google, so it compares the name without version tokens: ``gemini-flash-latest`` accepts
``gemini-3.8-flash`` but not ``gemini-3.8-flash-lite``.  A retired model that Google
routes to its successor therefore fails: the bound model did not answer.
"""
import hashlib
import re
from urllib.parse import quote

from spikes.direct_provider import (_MODEL_ID, DirectBinding, DirectResponseError,
                                    ProviderSpec, register_direct)


_PREFIX = 'models/'
_ENUM = re.compile(r'[A-Z][A-Z0-9_]{0,63}')
_VERSION_TOKEN = re.compile(r'\d+(\.\d+)*|preview|exp|experimental')
# The Model resource has no modality field; these name tokens come from the models page.
_NON_TEXT_TOKENS = frozenset({'audio', 'banana', 'embedding', 'image', 'live', 'tts'})


def _label(value):
    """Name a provider enum in an error without storing arbitrary response content."""
    return value if isinstance(value, str) and _ENUM.fullmatch(value) else 'UNKNOWN'


def _is_count(value):
    return type(value) is int and value >= 0


def _family(model):
    return [token for token in model.split('-')
            if token != 'latest' and not _VERSION_TOKEN.fullmatch(token)]


def _same_model(requested, served):
    if served == requested:
        return True
    if requested.endswith('-latest'):
        return _family(requested) == _family(served)
    head, tail = served[:len(requested)], served[len(requested):]
    return (head == requested and tail.startswith('-')
            and all(_VERSION_TOKEN.fullmatch(token) for token in tail[1:].split('-')))


def _part_text(parts):
    if not isinstance(parts, list):
        raise ValueError('Invalid Gemini content parts')
    texts = []
    for part in parts:
        if not isinstance(part, dict) or not isinstance(part.get('thought', False), bool):
            raise ValueError('Invalid Gemini content part')
        if part.get('thought', False):
            continue
        if not isinstance(part.get('text'), str):
            raise ValueError('Gemini returned a non-text part')
        texts.append(part['text'])
    return ''.join(texts)


def _candidate_text(candidate):
    content = candidate.get('content', {})
    if not isinstance(content, dict):
        raise ValueError('Invalid Gemini candidate content')
    return _part_text(content.get('parts', []))


def _is_block(feedback):
    return isinstance(feedback, dict) and 'blockReason' in feedback


def _check_prompt(value):
    feedback = value.get('promptFeedback', {})
    if not isinstance(feedback, dict):
        raise ValueError('Invalid Gemini prompt feedback')
    if _is_block(feedback):
        raise ValueError('Gemini blocked the prompt: ' + _label(feedback['blockReason']))


def _usage(value):
    usage = value.get('usageMetadata')
    if not isinstance(usage, dict):
        return None
    prompt = usage.get('promptTokenCount'); output = usage.get('candidatesTokenCount')
    total = usage.get('totalTokenCount'); thoughts = usage.get('thoughtsTokenCount', 0)
    if not all(_is_count(item) for item in (prompt, output, total, thoughts)):
        return None
    output += thoughts
    # The total may also count tool-use prompt tokens, but never less than these two.
    if total < prompt + output:
        return None
    return {'input_tokens': prompt, 'output_tokens': output, 'total_tokens': total}


def _auth_headers(secret):
    return {'x-goog-api-key': secret}


def _generate_path(model, stream):
    method = ':streamGenerateContent?alt=sse' if stream else ':generateContent'
    return '/v1beta/models/' + quote(model, safe='') + method


def _build_body(prompt, binding, output_format, stream):
    config = {'maxOutputTokens': binding.max_output_tokens}
    if output_format == 'json':
        config['responseMimeType'] = 'application/json'
    return {'contents': [{'role': 'user', 'parts': [{'text': prompt}]}],
            'generationConfig': config}


def _parse_response(value, binding):
    if not isinstance(value, dict):
        raise ValueError('Invalid Gemini response')
    _check_prompt(value)
    candidates = value.get('candidates')
    if not isinstance(candidates, list) or len(candidates) != 1 \
            or not isinstance(candidates[0], dict):
        raise ValueError('Gemini response requires exactly one candidate')
    candidate = candidates[0]
    reason = candidate.get('finishReason')
    if reason != 'STOP':
        raise ValueError('Gemini stopped with finish reason ' + _label(reason))
    served = value.get('modelVersion')
    if served is not None and not (isinstance(served, str) and _same_model(
            binding.model, served.removeprefix(_PREFIX))):
        raise ValueError('Gemini response came from a different model')
    text = _candidate_text(candidate)
    if not text:
        raise ValueError('Gemini response has no text')
    # The docs do not state responseId is always present, so it may be derived.
    identifier = value.get('responseId')
    if identifier is None:
        identifier = 'gemini-' + hashlib.sha256(text.encode()).hexdigest()[:32]
    elif not isinstance(identifier, str) or not identifier:
        raise ValueError('Invalid Gemini response ID')
    result = {'id': identifier, 'model': binding.model, 'response': text}
    usage = _usage(value)
    if usage is not None:
        result['usage'] = usage
    return result


def _stream_state():
    return {'text': [], 'finish': None, 'usage': None, 'model': None, 'id': None,
            'feedback': None}


def _stream_event(state, event):
    if 'error' in event:
        error = event['error']
        status = error.get('status') if isinstance(error, dict) else None
        raise DirectResponseError('Gemini stream reported error ' + _label(status))
    for source, key in (('usageMetadata', 'usage'), ('responseId', 'id')):
        if event.get(source) is not None:
            state[key] = event[source]
    # A block stays final, and feedback without a block must not read as completion.
    feedback = event.get('promptFeedback')
    if feedback is not None and not _is_block(state['feedback']):
        state['feedback'] = feedback
    served = event.get('modelVersion')
    if served is not None:
        if state['model'] is not None and state['model'] != served:
            raise ValueError('Gemini stream changed model')
        state['model'] = served
    candidates = event.get('candidates', [])
    if not isinstance(candidates, list) or len(candidates) > 1:
        raise ValueError('Gemini response requires exactly one candidate')
    if not candidates:
        return None
    candidate = candidates[0]
    if not isinstance(candidate, dict):
        raise ValueError('Invalid Gemini candidate')
    reason = candidate.get('finishReason')
    # A failure stays final: a later STOP must not hide it.
    if reason is not None and state['finish'] in (None, 'STOP'):
        state['finish'] = reason
    delta = _candidate_text(candidate)
    if not delta:
        return None
    state['text'].append(delta)
    return delta


def _stream_final(state):
    value = {}
    if state['feedback'] is not None:
        value['promptFeedback'] = state['feedback']
    if state['finish'] is None and not _is_block(state['feedback']):
        # Gemini sends no [DONE]; without a finish reason the stream may have been cut.
        raise ConnectionError('Gemini stream ended without a finish reason')
    value['candidates'] = [{'content': {'parts': [{'text': ''.join(state['text'])}]},
                            'finishReason': state['finish']}]
    for source, key in (('usageMetadata', 'usage'), ('modelVersion', 'model'),
                        ('responseId', 'id')):
        if state[key] is not None:
            value[source] = state[key]
    return value


def _models_path(cursor):
    # The models page caps pageSize at 1000.
    path = '/v1beta/models?pageSize=1000'
    return path if cursor is None else path + '&pageToken=' + quote(cursor, safe='')


def _parse_models(value):
    if not isinstance(value, dict) or not isinstance(value.get('models'), list):
        raise ValueError('Invalid Gemini model list')
    cursor = value.get('nextPageToken')
    if cursor is not None and not isinstance(cursor, str):
        raise ValueError('Invalid Gemini page token')
    items = []
    for model in value['models']:
        name = model.get('name') if isinstance(model, dict) else None
        methods = model.get('supportedGenerationMethods') if isinstance(model, dict) else None
        if not isinstance(name, str) or not name.startswith(_PREFIX) \
                or not _MODEL_ID.fullmatch(name[len(_PREFIX):]) \
                or not isinstance(methods, list) \
                or not all(isinstance(item, str) for item in methods):
            raise ValueError('Invalid Gemini model entry')
        model_id = name[len(_PREFIX):]
        if 'generateContent' not in methods \
                or _NON_TEXT_TOKENS & set(model_id.lower().split('-')):
            continue
        capabilities = {'generate-text', 'text-output', 'json-output'}
        # Reported only when listed: the docs never say generateContent implies streaming.
        if 'streamGenerateContent' in methods:
            capabilities.add('streaming')
        items.append({'model': model_id, 'capabilities': capabilities})
    return {'items': items, 'next_cursor': cursor or None}


SPEC = ProviderSpec(
    adapter_id='gemini-generate', provider_id='google', name='Gemini',
    host='generativelanguage.googleapis.com',
    endpoint='https://generativelanguage.googleapis.com/v1beta/models',
    protocol='gemini-generate-content-v1',
    auth_headers=_auth_headers, generate_path=_generate_path, build_body=_build_body,
    parse_response=_parse_response, stream_state=_stream_state, stream_event=_stream_event,
    stream_final=_stream_final, models_path=_models_path, parse_models=_parse_models)


class GeminiBinding(DirectBinding):
    spec = SPEC


register_direct(GeminiBinding)
