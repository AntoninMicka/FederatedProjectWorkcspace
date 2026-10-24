# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Bounded, explicitly approved retrieval of one public static source."""
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
import hashlib
import http.client
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import sqlite3
import ssl
import stat
import time
import zlib
from urllib.parse import urlsplit

from spikes.metadata import require, timestamp, uuid


MAX_WIRE_BYTES = 2 * 1024 * 1024
MAX_DECODED_BYTES = 2 * 1024 * 1024
MAX_TEXT_CHARS = 200_000
MAX_PROJECTION_BLOCKS = 2048
MAX_TABLE_ROWS = 512
MAX_TABLE_CELLS = 4096
MAX_PROJECTION_BYTES = 2 * 1024 * 1024
MAX_COMPRESSION_RATIO = 100
MAX_HEADER_VALUE = 8192
MAX_PURPOSE_BYTES = 4096
MAX_URL_BYTES = 8192
ALLOWED_PRIVACY = {'public', 'project', 'confidential'}
ALLOWED_MIME = {'text/html', 'text/plain'}
RESULT_STATES = {'succeeded', 'unsupported', 'rejected', 'failed', 'unknown'}
ALLOWLISTED_HEADERS = ('content-type', 'content-language', 'content-length',
                       'content-encoding', 'date', 'etag', 'last-modified',
                       'vary', 'cache-control', 'retry-after', 'location')


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':')).encode('utf-8')


def _digest(value):
    return hashlib.sha256(value).hexdigest()


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def _text(value, label, limit, *, empty=False):
    require(isinstance(value, str) and '\0' not in value
            and len(value.encode('utf-8')) <= limit
            and (empty or bool(value.strip())), f'Invalid public source {label}')
    return value.strip()


def _public_address(value):
    address = ipaddress.ip_address(value)
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    require(address.is_global and not any((address.is_private, address.is_loopback,
            address.is_link_local, address.is_multicast, address.is_reserved,
            address.is_unspecified)), 'Public source resolved to a non-public address')
    return address


def _origin(value):
    value = _text(value, 'origin', MAX_URL_BYTES)
    parsed = urlsplit(value)
    require(parsed.scheme == 'https' and parsed.hostname and not parsed.username
            and not parsed.password and not parsed.query and not parsed.fragment
            and parsed.path in {'', '/'} and parsed.port in {None, 443},
            'Public source origin must be HTTPS on port 443')
    try:
        ipaddress.ip_address(parsed.hostname)
    except ValueError:
        pass
    else:
        raise ValueError('Public source origin cannot use an IP literal')
    host = parsed.hostname.encode('idna').decode('ascii').lower()
    require(host == parsed.hostname.lower(), 'Public source origin must use canonical IDNA')
    return 'https://' + host


def normalize_url(value):
    value = _text(value, 'URL', MAX_URL_BYTES)
    parsed = urlsplit(value)
    require(parsed.scheme == 'https' and parsed.hostname and not parsed.username
            and not parsed.password and parsed.port in {None, 443}
            and not parsed.fragment, 'Public source URL must be public HTTPS without credentials')
    origin = _origin('https://' + parsed.hostname)
    path = parsed.path or '/'
    require(path.startswith('//') is False and '\\' not in path
            and all(ord(char) >= 0x20 for char in path), 'Invalid public source URL path')
    try: (path + (('?' + parsed.query) if parsed.query else '')).encode('ascii')
    except UnicodeEncodeError as exc:
        raise ValueError('Public source URL must be percent-encoded ASCII') from exc
    return origin + path + (('?' + parsed.query) if parsed.query else '')


def url_origin(value):
    parsed = urlsplit(value)
    require(parsed.hostname is not None, 'Public source URL has no hostname')
    return _origin('https://' + parsed.hostname)


class PublicSourceError(RuntimeError):
    state = 'failed'
    code = 'fetch-failed'

    def __init__(self, message, *, code=None):
        super().__init__(message)
        if code is not None: self.code = code


class PublicSourceUnsupported(PublicSourceError):
    state = 'unsupported'
    code = 'unsupported'


class PublicSourceRejected(PublicSourceError):
    state = 'rejected'
    code = 'rejected'


class PublicSourceUnknown(PublicSourceError):
    state = 'unknown'
    code = 'outcome-unknown'


class _TransportUnknown(PublicSourceUnknown):
    pass


@dataclass(frozen=True)
class PublicSourceBinding:
    binding_id: str
    revision: str
    origins: tuple
    user_agent: str
    max_wire_bytes: int
    max_decoded_bytes: int
    max_text_chars: int
    max_compression_ratio: int
    timeout_seconds: int

    adapter_id = 'static-html-v1'

    @classmethod
    def parse(cls, value):
        required = {'schema_version', 'binding_id', 'revision', 'adapter', 'origins',
                    'user_agent', 'auth', 'max_wire_bytes', 'max_decoded_bytes',
                    'max_text_chars', 'max_compression_ratio', 'timeout_seconds'}
        require(isinstance(value, dict) and set(value) == required,
                'Unknown or missing public source binding field')
        require(value['schema_version'] == 1 and value['adapter'] == cls.adapter_id
                and value['auth'] == 'none', 'Unsupported public source binding')
        uuid(value['binding_id'])
        revision = _text(value['revision'], 'binding revision', 256)
        user_agent = _text(value['user_agent'], 'User-Agent', 512)
        require(not any(char in user_agent for char in '\r\n'),
                'Invalid public source User-Agent')
        require(isinstance(value['origins'], list) and 1 <= len(value['origins']) <= 16,
                'Public source binding requires bounded origins')
        origins = tuple(_origin(item) for item in value['origins'])
        require(len(set(origins)) == len(origins), 'Duplicate public source origin')
        limits = (('max_wire_bytes', 1, MAX_WIRE_BYTES),
                  ('max_decoded_bytes', 1, MAX_DECODED_BYTES),
                  ('max_text_chars', 1, MAX_TEXT_CHARS),
                  ('max_compression_ratio', 1, MAX_COMPRESSION_RATIO),
                  ('timeout_seconds', 1, 15))
        for key, minimum, maximum in limits:
            require(type(value[key]) is int and minimum <= value[key] <= maximum,
                    f'Invalid public source {key}')
        return cls(value['binding_id'], revision, origins, user_agent,
                   value['max_wire_bytes'], value['max_decoded_bytes'],
                   value['max_text_chars'], value['max_compression_ratio'],
                   value['timeout_seconds'])

    def serialize(self):
        return {'schema_version': 1, 'binding_id': self.binding_id,
                'revision': self.revision, 'adapter': self.adapter_id,
                'origins': list(self.origins), 'user_agent': self.user_agent,
                'auth': 'none', 'max_wire_bytes': self.max_wire_bytes,
                'max_decoded_bytes': self.max_decoded_bytes,
                'max_text_chars': self.max_text_chars,
                'max_compression_ratio': self.max_compression_ratio,
                'timeout_seconds': self.timeout_seconds}


@dataclass(frozen=True)
class PublicSourceRequest:
    value: dict

    @classmethod
    def parse(cls, value):
        required = {'schema_version', 'run_id', 'task_id', 'user_id', 'project_id',
                    'privacy', 'expected_head', 'binding_id', 'binding_revision',
                    'adapter', 'candidate_source_id', 'candidate_url', 'purpose',
                    'accept', 'max_wire_bytes', 'max_decoded_bytes', 'max_text_chars',
                    'max_compression_ratio', 'timeout_seconds', 'created_at'}
        require(isinstance(value, dict) and set(value) == required,
                'Unknown or missing public source request field')
        require(value['schema_version'] == 1 and value['adapter'] == 'static-html-v1',
                'Unsupported public source request')
        for key in ('run_id', 'task_id', 'user_id', 'project_id'): uuid(value[key])
        require(value['privacy'] in ALLOWED_PRIVACY, 'Invalid public source privacy')
        require(isinstance(value['expected_head'], str)
                and bool(re.fullmatch(r'[0-9a-f]{40,64}', value['expected_head'])),
                'Invalid public source expected HEAD')
        uuid(value['binding_id'])
        _text(value['binding_revision'], 'binding revision', 256)
        _text(value['candidate_source_id'], 'candidate source ID', 256)
        normalized = normalize_url(value['candidate_url'])
        _text(value['purpose'], 'purpose', MAX_PURPOSE_BYTES)
        require(value['accept'] == ['text/html', 'text/plain'],
                'Unsupported public source Accept list')
        for key, maximum in (('max_wire_bytes', MAX_WIRE_BYTES),
                             ('max_decoded_bytes', MAX_DECODED_BYTES),
                             ('max_text_chars', MAX_TEXT_CHARS),
                             ('max_compression_ratio', MAX_COMPRESSION_RATIO),
                             ('timeout_seconds', 15)):
            require(type(value[key]) is int and 1 <= value[key] <= maximum,
                    f'Invalid public source {key}')
        timestamp(value['created_at'])
        normalized_value = dict(value, candidate_url=normalized)
        return cls(normalized_value)

    def serialize(self):
        return dict(self.value)


@dataclass(frozen=True)
class HTTPResult:
    status: int
    headers: dict
    body: bytes
    url: str


class _StructuredHTML(HTMLParser):
    hidden_tags = {'script', 'style', 'noscript', 'template', 'svg', 'canvas',
                   'iframe', 'object', 'head', 'header', 'nav', 'footer', 'aside',
                   'form'}
    hidden_classes = {'element-invisible', 'screen-reader-only', 'sr-only',
                      'visually-hidden', 'u-hidden'}
    content_tags = {'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'li', 'dt', 'dd',
                    'blockquote', 'pre'}
    boundary_tags = content_tags | {'table', 'tr', 'th', 'td', 'caption', 'ul', 'ol'}
    void_tags = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
                 'link', 'meta', 'param', 'source', 'track', 'wbr'}

    def __init__(self, limit):
        super().__init__(convert_charrefs=True)
        self.limit = limit; self.hidden = 0; self.stack = []; self.in_title = False
        self.title_parts = []; self.loose = []; self.captures = []; self.blocks = []
        self.heading_levels = [''] * 6; self.list_stack = []; self.table = None
        self.table_depth = 0; self.input_chars = 0; self.output_chars = 0
        self.anchor_counts = {}

    @staticmethod
    def _normalized(parts, *, preserve=False):
        value = (''.join(parts).replace('\ufeff', '').replace('\u200b', '')
                 .replace('\r\n', '\n').replace('\r', '\n'))
        if preserve:
            return '\n'.join(line.rstrip() for line in value.splitlines()).strip()
        return ' '.join(value.split())

    def _heading_path(self):
        return [value for value in self.heading_levels if value]

    def _add_block(self, block):
        if not block.get('text') and block['type'] != 'table': return
        require(len(self.blocks) < MAX_PROJECTION_BLOCKS,
                'Public source projection has too many blocks')
        identity = dict(block); base = _digest(_canonical(identity))
        occurrence = self.anchor_counts.get(base, 0) + 1
        self.anchor_counts[base] = occurrence
        anchor = 'block-' + base + ('' if occurrence == 1 else '-' + str(occurrence))
        value = {'anchor': anchor, **block}
        self.output_chars += (len(block.get('text', '')) + sum(
            len(cell) for row in block.get('rows', []) for cell in row))
        if self.output_chars > self.limit:
            raise PublicSourceUnsupported('Projected public source text is too large',
                                          code='text-too-large')
        self.blocks.append(value)

    def _flush_loose(self):
        value = self._normalized(self.loose); self.loose = []
        if value:
            self._add_block({'type': 'paragraph', 'text': value,
                             'heading_path': self._heading_path()})

    def _start_capture(self, tag, kind, **fields):
        self._flush_loose()
        self.captures.append({'tag': tag, 'type': kind, 'parts': [], **fields})

    def _finish_capture(self, tag):
        index = next((position for position in range(len(self.captures) - 1, -1, -1)
                      if self.captures[position]['tag'] == tag), None)
        if index is None: return
        capture = self.captures.pop(index)
        value = self._normalized(capture['parts'], preserve=capture['type'] == 'pre')
        if capture['type'] == 'table-cell':
            if self.table is not None and self.table.get('row') is not None:
                self.table['row'].append((value, capture['header']))
            return
        if capture['type'] == 'caption':
            if self.table is not None: self.table['caption'] = value
            return
        if not value: return
        if capture['type'] == 'heading':
            level = capture['level']
            self.heading_levels[level - 1] = value
            for offset in range(level, 6): self.heading_levels[offset] = ''
            self._add_block({'type': 'heading', 'level': level, 'text': value,
                             'heading_path': self._heading_path()})
        elif capture['type'] == 'list-item':
            self._add_block({'type': 'list-item', 'text': value,
                'ordered': capture['ordered'], 'depth': capture['depth'],
                'heading_path': capture['heading_path']})
        else:
            self._add_block({'type': capture['type'], 'text': value,
                             'heading_path': capture['heading_path']})

    def _finish_row(self):
        if self.table is None or self.table.get('row') is None: return
        row = self.table.pop('row')
        require(sum(len(item) for item in self.table['rows']) + len(row)
                <= MAX_TABLE_CELLS, 'Public source table has too many cells')
        if any(text for text, _ in row):
            index = len(self.table['rows'])
            self.table['rows'].append([text for text, _ in row])
            if row and all(header for _, header in row):
                self.table['header_rows'].append(index)

    def _finish_table(self):
        if self.table is None: return
        self._finish_capture('td'); self._finish_capture('th'); self._finish_row()
        table, self.table = self.table, None
        if table['rows']:
            self._add_block({'type': 'table', 'caption': table['caption'],
                'rows': table['rows'], 'header_rows': table['header_rows'],
                'heading_path': table['heading_path']})

    def handle_starttag(self, tag, attrs):
        tag = tag.lower(); attributes = {key.lower(): value for key, value in attrs}
        classes = set(str(attributes.get('class', '')).lower().split())
        style = re.sub(r'\s+', '', str(attributes.get('style', '')).lower())
        hidden = (tag in self.hidden_tags or 'hidden' in attributes
                  or str(attributes.get('aria-hidden', '')).lower() == 'true'
                  or str(attributes.get('role', '')).lower() == 'navigation'
                  or bool(classes & self.hidden_classes)
                  or 'display:none' in style or 'visibility:hidden' in style)
        if tag not in self.void_tags:
            self.stack.append((tag, hidden)); self.hidden += int(hidden)
        if len(self.stack) > 256:
            raise PublicSourceUnsupported('HTML nesting exceeds supported depth',
                                          code='html-too-deep')
        if tag == 'title': self.in_title = True
        if self.hidden: return
        if tag == 'br':
            target = self.captures[-1]['parts'] if self.captures else self.loose
            target.append('\n'); return
        if tag in {'ul', 'ol'}:
            if self.captures and self.captures[-1]['type'] == 'list-item':
                self._finish_capture(self.captures[-1]['tag'])
            self._flush_loose(); self.list_stack.append(tag == 'ol'); return
        if tag == 'table':
            self._flush_loose()
            if self.table is None:
                self.table = {'caption': '', 'rows': [], 'header_rows': [],
                              'heading_path': self._heading_path()}
                self.table_depth = 1
            else: self.table_depth += 1
            return
        if self.table is not None:
            if self.table_depth > 1: return
            if tag == 'tr':
                self._finish_row()
                require(len(self.table['rows']) < MAX_TABLE_ROWS,
                        'Public source table has too many rows')
                self.table['row'] = []
            elif tag in {'th', 'td'}:
                self._finish_capture('th'); self._finish_capture('td')
                if self.table.get('row') is None: self.table['row'] = []
                self._start_capture(tag, 'table-cell', header=tag == 'th')
            elif tag == 'caption': self._start_capture(tag, 'caption')
            return
        if tag in self.content_tags:
            if self.captures and self.captures[-1]['type'] == 'list-item' and tag != 'li':
                # Cards are commonly encoded as <li> with a heading and paragraphs
                # inside. Keep the card as one coherent list item instead of emitting
                # a heading followed by text assigned to the previous heading path.
                self.captures[-1]['parts'].append('\n')
                return
            if tag[0] == 'h' and tag[1:].isdigit():
                self._start_capture(tag, 'heading', level=int(tag[1:]))
            elif tag == 'li':
                self._start_capture(tag, 'list-item',
                    ordered=self.list_stack[-1] if self.list_stack else False,
                    depth=max(1, len(self.list_stack)), heading_path=self._heading_path())
            elif not self.captures:
                kind = {'p': 'paragraph', 'dt': 'definition-term',
                        'dd': 'definition-description'}.get(tag, tag)
                self._start_capture(tag, kind, heading_path=self._heading_path())

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag.lower() not in self.void_tags: self.handle_endtag(tag)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == 'title': self.in_title = False
        if not self.hidden:
            if self.table is not None:
                if tag in {'td', 'th', 'caption'}: self._finish_capture(tag)
                elif tag == 'tr': self._finish_row()
                elif tag == 'table':
                    self.table_depth -= 1
                    if self.table_depth == 0: self._finish_table()
            else:
                if (tag in self.content_tags and self.captures
                        and self.captures[-1]['type'] == 'list-item' and tag != 'li'):
                    self.captures[-1]['parts'].append('\n')
                elif tag in self.content_tags:
                    self._finish_capture(tag)
                if tag in {'ul', 'ol'} and self.list_stack:
                    self.list_stack.pop(); self._flush_loose()
        if tag not in self.void_tags:
            match = next((position for position in range(len(self.stack) - 1, -1, -1)
                          if self.stack[position][0] == tag), None)
            if match is not None:
                removed = self.stack[match:]; del self.stack[match:]
                self.hidden = max(0, self.hidden - sum(item[1] for item in removed))

    def handle_data(self, data):
        self.input_chars += len(data)
        if self.input_chars > self.limit * 4 + 16_384:
            raise PublicSourceUnsupported('Projected public source text is too large',
                                          code='text-too-large')
        if self.in_title: self.title_parts.append(data); return
        if self.hidden: return
        if self.captures: self.captures[-1]['parts'].append(data)
        elif self.table is None: self.loose.append(data)

    def projection(self):
        for tag in [item['tag'] for item in reversed(self.captures)]:
            self._finish_capture(tag)
        self._finish_table(); self._flush_loose()
        if not self.blocks:
            raise PublicSourceUnsupported(
                'Static page contains no supported visible body text',
                code='no-static-text')
        return {'schema_version': 1, 'kind': 'public-source-structured-v1',
                'mime': 'text/html', 'title': self._normalized(self.title_parts) or None,
                'blocks': self.blocks, 'warnings': []}


def _render_projection(projection):
    parts = []
    if projection['title']: parts.append(projection['title'])
    for block in projection['blocks']:
        kind = block['type']
        if kind == 'heading': value = '#' * block['level'] + ' ' + block['text']
        elif kind == 'list-item':
            marker = '1.' if block['ordered'] else '-'
            value = '  ' * (block['depth'] - 1) + marker + ' ' + block['text']
        elif kind == 'blockquote':
            value = '\n'.join('> ' + line for line in block['text'].splitlines())
        elif kind == 'pre': value = block['text']
        elif kind == 'table':
            rows = [' | '.join(cell for cell in row) for row in block['rows']]
            value = (('Tabulka: ' + block['caption'] + '\n') if block['caption'] else '')
            value += '\n'.join(rows)
        elif kind == 'definition-term': value = block['text'] + ':'
        elif kind == 'definition-description': value = '  ' + block['text']
        else: value = block['text']
        if value: parts.append(value)
    return '\n\n'.join(parts).strip()


def _validate_projection(value):
    require(isinstance(value, dict) and set(value) == {
        'schema_version', 'kind', 'mime', 'title', 'blocks', 'warnings'},
        'Invalid structured public source projection')
    require(value['schema_version'] == 1
            and value['kind'] == 'public-source-structured-v1'
            and value['mime'] in ALLOWED_MIME
            and (value['title'] is None or isinstance(value['title'], str))
            and isinstance(value['warnings'], list) and not value['warnings']
            and isinstance(value['blocks'], list)
            and 0 < len(value['blocks']) <= MAX_PROJECTION_BLOCKS,
            'Invalid structured public source projection')
    counts = {}
    for block in value['blocks']:
        require(isinstance(block, dict) and isinstance(block.get('anchor'), str)
                and isinstance(block.get('heading_path'), list)
                and all(isinstance(item, str) for item in block['heading_path']),
                'Invalid structured public source block')
        identity = dict(block); anchor = identity.pop('anchor')
        kind = identity.get('type')
        base_fields = {'type', 'heading_path'}
        if kind == 'heading':
            expected = base_fields | {'level', 'text'}
            require(type(identity.get('level')) is int and 1 <= identity['level'] <= 6,
                    'Invalid structured public source heading')
        elif kind == 'list-item':
            expected = base_fields | {'ordered', 'depth', 'text'}
            require(type(identity.get('ordered')) is bool
                    and type(identity.get('depth')) is int
                    and 1 <= identity['depth'] <= 256,
                    'Invalid structured public source list item')
        elif kind == 'table':
            expected = base_fields | {'caption', 'rows', 'header_rows'}
            require(isinstance(identity.get('caption'), str)
                    and isinstance(identity.get('rows'), list)
                    and 0 < len(identity['rows']) <= MAX_TABLE_ROWS
                    and all(isinstance(row, list) and row
                            and all(isinstance(cell, str) for cell in row)
                            for row in identity['rows'])
                    and sum(len(row) for row in identity['rows']) <= MAX_TABLE_CELLS
                    and isinstance(identity.get('header_rows'), list)
                    and all(type(item) is int and 0 <= item < len(identity['rows'])
                            for item in identity['header_rows']),
                    'Invalid structured public source table')
        else:
            require(kind in {'paragraph', 'blockquote', 'pre', 'definition-term',
                             'definition-description'},
                    'Invalid structured public source block type')
            expected = base_fields | {'text'}
        require(set(identity) == expected, 'Unknown structured public source block field')
        if 'text' in identity:
            require(isinstance(identity['text'], str) and bool(identity['text']),
                    'Invalid structured public source block text')
        base = _digest(_canonical(identity)); occurrence = counts.get(base, 0) + 1
        counts[base] = occurrence
        expected_anchor = ('block-' + base
                           + ('' if occurrence == 1 else '-' + str(occurrence)))
        require(anchor == expected_anchor, 'Structured public source anchor changed')
    return value


def project_document(body, content_type, limit):
    pieces = [item.strip() for item in content_type.split(';')]
    mime = pieces[0].lower()
    require(mime in ALLOWED_MIME, 'Unsupported public source MIME')
    charset = None
    for item in pieces[1:]:
        if item.lower().startswith('charset='):
            charset = item.split('=', 1)[1].strip(' \t\"\'').lower()
    if charset not in {None, '', 'utf-8', 'utf8'}:
        raise PublicSourceUnsupported('Unsupported public source charset',
                                      code='unsupported-charset')
    try: decoded = body.decode('utf-8')
    except UnicodeDecodeError as exc:
        raise PublicSourceUnsupported('Public source is not valid UTF-8',
                                      code='invalid-utf8') from exc
    if mime == 'text/plain':
        text = '\n'.join(' '.join(line.split()) for line in decoded.splitlines()).strip()
        if len(text) > limit:
            raise PublicSourceUnsupported('Projected public source text is too large',
                                          code='text-too-large')
        blocks = []
        anchor_counts = {}
        for paragraph in re.split(r'\n\s*\n', decoded):
            value = ' '.join(paragraph.split())
            if not value: continue
            identity = {'type': 'paragraph', 'text': value, 'heading_path': []}
            base = _digest(_canonical(identity))
            occurrence = anchor_counts.get(base, 0) + 1
            anchor_counts[base] = occurrence
            anchor = ('block-' + base
                      + ('' if occurrence == 1 else '-' + str(occurrence)))
            blocks.append({'anchor': anchor, **identity})
        require(blocks, 'Static page contains no supported visible text')
        projection = {'schema_version': 1, 'kind': 'public-source-structured-v1',
            'mime': mime, 'title': None, 'blocks': blocks, 'warnings': []}
        return text, _validate_projection(projection)
    parser = _StructuredHTML(limit)
    try: parser.feed(decoded); parser.close(); projection = parser.projection()
    except PublicSourceError: raise
    except Exception as exc:
        raise PublicSourceUnsupported('Malformed HTML is unsupported',
                                      code='malformed-html') from exc
    text = _render_projection(projection)
    if len(text) > limit:
        raise PublicSourceUnsupported('Projected public source text is too large',
                                      code='text-too-large')
    return text, _validate_projection(projection)


def project_text(body, content_type, limit):
    return project_document(body, content_type, limit)[0]


def _robots_allowed(raw, path, user_agent):
    try: text = raw.decode('utf-8')
    except UnicodeDecodeError as exc:
        raise PublicSourceRejected('robots.txt is not valid UTF-8',
                                   code='robots-invalid') from exc
    token = user_agent.split('/', 1)[0].lower()
    groups, agents, rules = [], [], []
    for raw_line in text.splitlines():
        line = raw_line.split('#', 1)[0].strip()
        if not line or ':' not in line: continue
        key, value = (part.strip() for part in line.split(':', 1))
        key = key.lower()
        if key == 'user-agent':
            if rules: groups.append((agents, rules)); agents, rules = [], []
            agents.append(value.lower())
        elif key in {'allow', 'disallow'} and agents:
            rules.append((key == 'allow', value))
    if agents: groups.append((agents, rules))
    exact = [rules for agents, rules in groups if token in agents]
    candidates = exact or [rules for agents, rules in groups if '*' in agents]
    matches = []
    for rules in candidates:
        for allow, pattern in rules:
            if pattern == '': continue
            expression = re.escape(pattern).replace(r'\*', '.*')
            if expression.endswith(r'\$'): expression = expression[:-2] + '$'
            if re.match(expression, path): matches.append((len(pattern), allow))
    if not matches: return True
    longest = max(length for length, _ in matches)
    return any(allow for length, allow in matches if length == longest)


class PublicSourceRuns:
    """Authoritative node-local journal for a single approved fetch effect."""
    def __init__(self, state_dir):
        self.root = Path(state_dir).absolute()
        info = self.root.lstat()
        require(stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode)
                and info.st_uid == os.getuid()
                and stat.S_IMODE(info.st_mode) == 0o700,
                'Public source state requires owned mode 0700')
        self.path = self.root / 'public-source-runs.sqlite'
        self.staging = self.root / 'public-source-staging'

    def connect(self):
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        info = os.fstat(fd); os.close(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                and info.st_nlink == 1 and not info.st_mode & 0o077,
                'Unsafe public source journal')
        db = sqlite3.connect(self.path, timeout=30)
        db.execute('PRAGMA synchronous=FULL')
        db.execute('''CREATE TABLE IF NOT EXISTS runs(
            run_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, node_id TEXT NOT NULL,
            user_id TEXT NOT NULL, project_id TEXT NOT NULL, request_json TEXT NOT NULL,
            request_digest TEXT NOT NULL, preview_json TEXT NOT NULL,
            preview_sha256 TEXT NOT NULL, binding_json TEXT NOT NULL, state TEXT NOT NULL,
            result_json TEXT, error TEXT, error_code TEXT)''')
        columns = [row[1] for row in db.execute('PRAGMA table_info(runs)')]
        require(columns == ['run_id', 'task_id', 'node_id', 'user_id', 'project_id',
            'request_json', 'request_digest', 'preview_json', 'preview_sha256',
            'binding_json', 'state', 'result_json', 'error', 'error_code'],
            'Unknown public source run schema')
        db.commit(); return closing(db)

    @staticmethod
    def _row(row):
        if row is None: return None
        return {'run_id': row[0], 'task_id': row[1], 'node_id': row[2],
                'user_id': row[3], 'project_id': row[4], 'request': json.loads(row[5]),
                'request_digest': row[6], 'preview': json.loads(row[7]),
                'preview_sha256': row[8], 'binding': json.loads(row[9]),
                'state': row[10],
                'result': None if row[11] is None else json.loads(row[11]),
                'error': row[12], 'error_code': row[13]}

    def get(self, run_id):
        uuid(run_id)
        with self.connect() as db:
            row = db.execute('SELECT * FROM runs WHERE run_id=?', (run_id,)).fetchone()
        return self._row(row)

    def for_task(self, task_id, node_id, user_id):
        for value in (task_id, node_id, user_id): uuid(value)
        with self.connect() as db:
            rows = db.execute('SELECT * FROM runs WHERE task_id=? ORDER BY rowid',
                              (task_id,)).fetchall()
        result = []
        for row in rows:
            require(row[2:4] == (node_id, user_id),
                    'Public source runs are unavailable to this user')
            result.append(self._row(row))
        return result

    def prepare(self, *, request, preview, binding, node_id):
        require(isinstance(request, PublicSourceRequest), 'Validated public source request required')
        require(isinstance(binding, PublicSourceBinding), 'Validated public source binding required')
        uuid(node_id)
        value = request.serialize()
        require(value['binding_id'] == binding.binding_id
                and value['binding_revision'] == binding.revision
                and value['adapter'] == binding.adapter_id
                and url_origin(value['candidate_url']) in binding.origins,
                'Public source request does not match binding')
        for key in ('max_wire_bytes', 'max_decoded_bytes', 'max_text_chars',
                    'max_compression_ratio', 'timeout_seconds'):
            require(value[key] <= getattr(binding, key),
                    'Public source request exceeds binding limits')
        raw_request = _canonical(value).decode(); raw_preview = _canonical(preview).decode()
        identity = (value['task_id'], node_id, value['user_id'], value['project_id'],
                    raw_request, _digest(raw_request.encode()), raw_preview,
                    _digest(raw_preview.encode()), _canonical(binding.serialize()).decode())
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT task_id,node_id,user_id,project_id,request_json,'
                'request_digest,preview_json,preview_sha256,binding_json FROM runs '
                'WHERE run_id=?', (value['run_id'],)).fetchone()
            if row: require(row == identity, 'Public source run ID belongs to another request')
            else:
                db.execute('INSERT INTO runs VALUES(?,?,?,?,?,?,?,?,?,?,?,NULL,NULL,NULL)',
                           (value['run_id'],) + identity + ('prepared',))
            db.commit()
        return self.get(value['run_id'])

    def transition(self, run_id, old, new, *, result=None, error=None, code=None):
        require(new in {'dispatching'} | RESULT_STATES, 'Invalid public source run state')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            changed = db.execute('UPDATE runs SET state=?,result_json=?,error=?,error_code=? '
                'WHERE run_id=? AND state=?', (new, None if result is None else
                _canonical(result).decode(), error, code, run_id, old)).rowcount
            require(changed == 1, 'Public source run state changed concurrently')
            db.commit()
        return self.get(run_id)

    def write_staging(self, run_id, raw, projected, structured=None):
        uuid(run_id)
        require(isinstance(raw, bytes) and isinstance(projected, bytes)
                and (structured is None or isinstance(structured, bytes)),
                'Public source staging requires bytes')
        self.staging.mkdir(mode=0o700, exist_ok=True)
        require(stat.S_IMODE(self.staging.stat().st_mode) == 0o700,
                'Unsafe public source staging directory')
        folder = self.staging / run_id
        folder.mkdir(mode=0o700, exist_ok=True)
        files = [('raw.bin', raw), ('projection.txt', projected)]
        if structured is not None:
            require(len(structured) <= MAX_PROJECTION_BYTES,
                    'Structured public source projection is too large')
            files.append(('projection.json', structured))
        for name, data in files:
            temporary = folder / ('.' + name + '.tmp')
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            try:
                with os.fdopen(fd, 'wb', closefd=False) as stream:
                    stream.write(data); stream.flush(); os.fsync(stream.fileno())
                os.close(fd); fd = -1
                os.replace(temporary, folder / name)
            finally:
                if fd >= 0: os.close(fd)
                if temporary.exists(): temporary.unlink()
        directory = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(directory)
        finally: os.close(directory)
        parent = os.open(self.staging, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(parent)
        finally: os.close(parent)
        result = {'raw_file': 'raw.bin', 'text_file': 'projection.txt',
                  'raw_sha256': _digest(raw), 'text_sha256': _digest(projected)}
        if structured is not None:
            result.update(projection_file='projection.json',
                          projection_sha256=_digest(structured))
        return result

    def read_staging(self, run_id):
        row = self.get(run_id)
        require(row is not None and row['state'] == 'succeeded' and row['result'],
                'Public source result is not available')
        folder = self.staging / run_id
        values = []
        for name, key in (('raw.bin', 'raw_sha256'), ('projection.txt', 'text_sha256')):
            data = self._read_staging_file(folder / name)
            require(_digest(data) == row['result']['staging'][key],
                    'Public source staging hash mismatch')
            values.append(data)
        return tuple(values)

    def read_structured(self, run_id):
        row = self.get(run_id)
        require(row is not None and row['state'] == 'succeeded' and row['result'],
                'Public source result is not available')
        staging = row['result'].get('staging', {})
        if 'projection_file' not in staging:
            return None
        require(staging.get('projection_file') == 'projection.json'
                and isinstance(staging.get('projection_sha256'), str),
                'Invalid structured public source staging descriptor')
        data = self._read_staging_file(self.staging / run_id / 'projection.json')
        require(len(data) <= MAX_PROJECTION_BYTES
                and _digest(data) == staging['projection_sha256'],
                'Public source structured staging hash mismatch')
        try: value = json.loads(data)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError('Invalid structured public source staging') from exc
        return _validate_projection(value)

    @staticmethod
    def _read_staging_file(path):
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            info = os.fstat(fd)
            require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                    and info.st_nlink == 1 and not info.st_mode & 0o077,
                    'Unsafe public source staging file')
            chunks, total = [], 0
            while True:
                chunk = os.read(fd, 64 * 1024)
                if not chunk: break
                chunks.append(chunk); total += len(chunk)
                require(total <= MAX_WIRE_BYTES + MAX_DECODED_BYTES,
                        'Oversized public source staging file')
            return b''.join(chunks)
        finally: os.close(fd)

    def recover(self):
        recovered = []
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            rows = db.execute("SELECT run_id,state,result_json FROM runs WHERE state IN "
                              "('dispatching','succeeded')").fetchall()
            for run_id, state, result_json in rows:
                if state == 'dispatching':
                    db.execute("UPDATE runs SET state='unknown',error=?,error_code=? "
                               "WHERE run_id=? AND state='dispatching'",
                               ('Fetch was interrupted after dispatch', 'restart-unknown', run_id))
                    recovered.append(run_id); continue
                try:
                    result = json.loads(result_json); folder = self.staging / run_id
                    files = [('raw.bin', 'raw_sha256'),
                             ('projection.txt', 'text_sha256')]
                    staging = result['staging']
                    if 'projection_file' in staging:
                        require(staging.get('projection_file') == 'projection.json',
                                'Invalid structured public source staging descriptor')
                        files.append(('projection.json', 'projection_sha256'))
                    valid = all(
                        _digest(self._read_staging_file(folder / name)) == result['staging'][key]
                        for name, key in files)
                    if valid and 'projection_file' in staging:
                        _validate_projection(json.loads(
                            self._read_staging_file(folder / 'projection.json')))
                except (OSError, KeyError, TypeError, ValueError): valid = False
                if not valid:
                    db.execute("UPDATE runs SET state='failed',error=?,error_code=? "
                               "WHERE run_id=? AND state='succeeded'",
                               ('Durable fetch staging is missing or changed',
                                'staging-invalid', run_id))
                    recovered.append(run_id)
            db.commit()
        return recovered


class StaticHTMLAdapter:
    def __init__(self, runs, *, transport=None, resolver=None, now=_now,
                 monotonic=time.monotonic):
        require(isinstance(runs, PublicSourceRuns), 'Reader requires PublicSourceRuns')
        self.runs = runs; self.transport = transport
        self.resolver = resolver or socket.getaddrinfo; self.now = now
        self.monotonic = monotonic

    @staticmethod
    def _headers(headers):
        result = {}
        for key, value in headers.items():
            lowered = key.lower()
            if lowered in ALLOWLISTED_HEADERS:
                require(isinstance(value, str) and len(value) <= MAX_HEADER_VALUE
                        and not any(char in value for char in '\r\n'),
                        'Invalid public source response header')
                result[lowered] = value
        return result

    @staticmethod
    def _decode(result, request):
        encoding = result.headers.get('content-encoding', 'identity').lower().strip()
        if encoding in {'', 'identity'}: decoded = result.body
        elif encoding == 'gzip':
            try:
                inflater = zlib.decompressobj(16 + zlib.MAX_WBITS)
                decoded = inflater.decompress(result.body,
                                              request['max_decoded_bytes'] + 1)
                if (len(decoded) <= request['max_decoded_bytes']
                        and not inflater.eof):
                    decoded += inflater.flush(request['max_decoded_bytes'] + 1 - len(decoded))
                if not inflater.eof:
                    raise PublicSourceUnsupported(
                        'Decoded public source exceeds limit', code='decoded-too-large')
            except PublicSourceError: raise
            except (OSError, EOFError, zlib.error) as exc:
                raise PublicSourceUnsupported('Invalid gzip public source response',
                                              code='invalid-compression') from exc
        else:
            raise PublicSourceUnsupported('Unsupported public source content encoding',
                                          code='unsupported-encoding')
        if len(decoded) > request['max_decoded_bytes']:
            raise PublicSourceUnsupported('Decoded public source exceeds limit',
                                          code='decoded-too-large')
        if (encoding == 'gzip' and len(decoded) > 64 * 1024
                and len(decoded) > max(1, len(result.body))
                * request['max_compression_ratio']):
            raise PublicSourceUnsupported('Public source compression ratio exceeds limit',
                                          code='compression-ratio')
        return decoded

    def dispatch(self, run_id, binding, *, preview_sha256):
        row = self.runs.get(run_id)
        require(row is not None and row['preview_sha256'] == preview_sha256,
                'Public source preview changed before dispatch')
        require(row['binding'] == binding.serialize(),
                'Public source binding changed before dispatch')
        if row['state'] == 'succeeded':
            self.runs.read_staging(run_id); return row['result']
        if row['state'] in {'dispatching', 'unknown'}:
            raise PublicSourceUnknown('Public source outcome is unknown; retry is forbidden',
                                      code=row['error_code'] or 'outcome-unknown')
        if row['state'] != 'prepared':
            raise PublicSourceError(row['error'] or 'Public source run is closed',
                                    code=row['error_code'] or row['state'])
        request = PublicSourceRequest.parse(row['request']).serialize()
        self.runs.transition(run_id, 'prepared', 'dispatching')
        try:
            deadline = self.monotonic() + request['timeout_seconds']
            robots = self._fetch(binding, request, 'robots', deadline)
            if robots.status == 200:
                if len(robots.body) > request['max_wire_bytes']:
                    raise PublicSourceRejected('robots.txt exceeds fetch limit',
                                               code='robots-too-large')
                path = urlsplit(request['candidate_url']).path or '/'
                if not _robots_allowed(robots.body, path, binding.user_agent):
                    raise PublicSourceRejected('robots.txt disallows this fetch',
                                               code='robots-disallowed')
            elif 400 <= robots.status < 500 and robots.status != 429:
                pass
            else:
                raise PublicSourceRejected('robots.txt is unavailable',
                                           code='robots-unavailable')
            target = self._fetch(binding, request, 'target', deadline)
            if target.url != request['candidate_url']:
                raise PublicSourceRejected('Public source transport changed the approved URL',
                                           code='target-changed')
            if 300 <= target.status < 400:
                raise PublicSourceRejected('Public source redirect requires a new preview',
                                           code='redirect-requires-approval')
            if target.status in {401, 403}:
                raise PublicSourceUnsupported('Public source requires access credentials',
                                              code='authentication-required')
            if target.status in {429, 503}:
                raise PublicSourceError(f'Public source returned HTTP {target.status}',
                                        code='overloaded')
            if target.status != 200:
                raise PublicSourceError(f'Public source returned HTTP {target.status}',
                                        code='http-error')
            if len(target.body) > request['max_wire_bytes']:
                raise PublicSourceUnsupported('Public source wire response exceeds limit',
                                              code='wire-too-large')
            headers = self._headers(target.headers)
            if 'content-length' in headers:
                try: declared_length = int(headers['content-length'])
                except ValueError as exc:
                    raise PublicSourceUnsupported('Invalid public source Content-Length',
                                                  code='invalid-content-length') from exc
                if declared_length < 0 or declared_length > request['max_wire_bytes']:
                    raise PublicSourceUnsupported('Public source Content-Length exceeds limit',
                                                  code='wire-too-large')
                if declared_length != len(target.body):
                    raise PublicSourceUnsupported('Public source Content-Length does not match',
                                                  code='content-length-mismatch')
            content_type = headers.get('content-type', '')
            if content_type.split(';', 1)[0].strip().lower() not in ALLOWED_MIME:
                raise PublicSourceUnsupported('Unsupported public source MIME',
                                              code='unsupported-mime')
            decoded = self._decode(HTTPResult(target.status, headers, target.body,
                                              target.url), request)
            projected, structured = project_document(
                decoded, content_type, request['max_text_chars'])
            if not projected:
                raise PublicSourceUnsupported(
                    'Static page contains no supported visible text', code='no-static-text')
            projected_bytes = projected.encode('utf-8')
            structured_bytes = _canonical(structured)
            staging = self.runs.write_staging(
                run_id, target.body, projected_bytes, structured_bytes)
            result = {'schema_version': 2, 'state': 'succeeded', 'run_id': run_id,
                'request_digest': row['request_digest'],
                'requested_url': request['candidate_url'], 'final_url': target.url,
                'fetched_at': self.now(), 'http_status': target.status,
                'headers': headers, 'raw_length': len(target.body),
                'raw_sha256': _digest(target.body), 'text_length': len(projected),
                'text_sha256': _digest(projected_bytes), 'adapter': binding.adapter_id,
                'binding_id': binding.binding_id, 'binding_revision': binding.revision,
                'external_identity': None, 'external_revision': headers.get('etag')
                    or headers.get('last-modified'), 'external_time': headers.get('date'),
                'license': None, 'warnings': ['Remote content is untrusted data.'],
                'truncated': False, 'staging': staging,
                'projection': {'schema': structured['kind'],
                    'sha256': _digest(structured_bytes),
                    'block_count': len(structured['blocks'])},
                'context_input': {'schema_version': 1, 'kind': 'public-source-run',
                    'run_id': run_id, 'adapter': binding.adapter_id,
                    'adapter_revision': binding.revision,
                    'raw_sha256': _digest(target.body),
                    'text_sha256': _digest(projected_bytes),
                    'projection_schema': structured['kind'],
                    'projection_sha256': _digest(structured_bytes),
                    'source_url': request['candidate_url'],
                    'privacy': request['privacy'], 'untrusted': True}}
        except PublicSourceError as exc:
            self.runs.transition(run_id, 'dispatching', exc.state,
                                 error=str(exc), code=exc.code)
            raise
        except Exception as exc:
            self.runs.transition(run_id, 'dispatching', 'unknown',
                                 error=type(exc).__name__, code='transport-unknown')
            raise PublicSourceUnknown('Public source outcome is unknown',
                                      code='transport-unknown') from exc
        self.runs.transition(run_id, 'dispatching', 'succeeded', result=result)
        return result

    @staticmethod
    def _resolve(host, resolver):
        try: rows = resolver(host, 443, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise PublicSourceError('Public source DNS resolution failed',
                                    code='dns-failed') from exc
        require(rows, 'Public source DNS returned no address')
        addresses = []
        for family, socktype, protocol, canonname, sockaddr in rows:
            address = _public_address(sockaddr[0])
            if (family, str(address)) not in addresses: addresses.append((family, str(address)))
        return addresses

    def _fetch(self, binding, request, phase, deadline):
        require(phase in {'robots', 'target'}, 'Invalid public source fetch phase')
        require(url_origin(request['candidate_url']) in binding.origins,
                'Public source origin is not allowed')
        if self.monotonic() >= deadline:
            raise PublicSourceError('Public source total deadline expired',
                                    code='fetch-timeout')
        url = (url_origin(request['candidate_url']) + '/robots.txt'
               if phase == 'robots' else request['candidate_url'])
        if self.transport is not None:
            return self.transport(binding, request, self.resolver, phase)
        return self._get(url, binding, self.resolver, deadline, self.monotonic)

    @classmethod
    def _get(cls, url, binding, resolver, deadline, monotonic):
        parsed = urlsplit(url); addresses = cls._resolve(parsed.hostname, resolver)
        family, address = addresses[0]
        sock = None; sent = False
        def remaining():
            value = deadline - monotonic()
            if value <= 0:
                raise TimeoutError('public source total deadline expired')
            return value
        try:
            sock = socket.socket(family, socket.SOCK_STREAM)
            sock.settimeout(remaining())
            sock.connect((address, 443, 0, 0) if family == socket.AF_INET6 else (address, 443))
            context = ssl.create_default_context()
            sock.settimeout(remaining())
            sock = context.wrap_socket(sock, server_hostname=parsed.hostname)
            target = parsed.path or '/'
            if parsed.query: target += '?' + parsed.query
            request = (f'GET {target} HTTP/1.1\r\nHost: {parsed.hostname}\r\n'
                       f'User-Agent: {binding.user_agent}\r\n'
                       'Accept: text/html, text/plain\r\nAccept-Encoding: '
                       + ('identity' if parsed.path == '/robots.txt' else 'gzip, identity')
                       + '\r\n'
                       'Connection: close\r\n\r\n').encode('ascii')
            sock.settimeout(remaining()); sock.sendall(request); sent = True
            sock.settimeout(remaining())
            response = http.client.HTTPResponse(sock, method='GET'); response.begin()
            headers = {key.lower(): value for key, value in response.getheaders()}
            sock.settimeout(remaining())
            raw = response.read(binding.max_wire_bytes + 1)
            return HTTPResult(response.status, headers, raw, url)
        except PublicSourceError: raise
        except (ssl.SSLError, ssl.CertificateError) as exc:
            if sent: raise _TransportUnknown('TLS response was interrupted', code='tls-unknown') from exc
            raise PublicSourceError('Public source TLS validation failed', code='tls-failed') from exc
        except (TimeoutError, OSError, http.client.HTTPException) as exc:
            if sent: raise _TransportUnknown('Public source response was interrupted',
                                             code='response-unknown') from exc
            raise PublicSourceError('Public source connection failed', code='connect-failed') from exc
        finally:
            if sock is not None:
                try: sock.close()
                except OSError:
                    pass
