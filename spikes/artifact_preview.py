# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
#
"""Bounded, read-only previews of committed artifact bytes; no external URLs."""
import base64
from html.parser import HTMLParser
import json
from pathlib import PurePosixPath
import re
import subprocess

from spikes.metadata import require

MAX_PREVIEW = 4 * 1024 * 1024
MAX_PREVIEW_LINES = 2000


def _unique_json_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('Duplicate JSON key')
        value[key] = item
    return value


class _SafeHTMLText(HTMLParser):
    """Extract visible text without ever handing imported markup to a renderer."""

    BLOCKS = {
        'address', 'article', 'aside', 'blockquote', 'br', 'dd', 'div', 'dl', 'dt',
        'figcaption', 'figure', 'footer', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
        'header', 'hr', 'li', 'main', 'nav', 'ol', 'p', 'pre', 'section', 'table',
        'tbody', 'td', 'tfoot', 'th', 'thead', 'tr', 'ul',
    }
    HIDDEN = {'head', 'iframe', 'noscript', 'script', 'style', 'svg', 'template'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden_depth = 0

    def _newline(self):
        if self.parts and self.parts[-1] != '\n':
            self.parts.append('\n')

    def handle_starttag(self, tag, attrs):
        tag = tag.casefold()
        if self.hidden_depth:
            if tag in self.HIDDEN:
                self.hidden_depth += 1
            return
        if tag in self.HIDDEN:
            self.hidden_depth = 1
        elif tag in self.BLOCKS:
            self._newline()

    def handle_startendtag(self, tag, attrs):
        if not self.hidden_depth and tag.casefold() in self.BLOCKS:
            self._newline()

    def handle_endtag(self, tag):
        tag = tag.casefold()
        if self.hidden_depth:
            if tag in self.HIDDEN:
                self.hidden_depth -= 1
            return
        if tag in self.BLOCKS:
            self._newline()

    def handle_data(self, data):
        if self.hidden_depth:
            return
        value = re.sub(r'\s+', ' ', data).strip()
        if not value:
            return
        if (self.parts and self.parts[-1] != '\n'
                and not value.startswith(('.', ',', ':', ';', '!', '?', ')', ']', '}'))
                and not self.parts[-1].endswith(('(', '[', '{', '/'))):
            self.parts.append(' ')
        self.parts.append(value)

    def text(self):
        lines = (' '.join(line.split()) for line in ''.join(self.parts).splitlines())
        return '\n'.join(line for line in lines if line).strip()


def _bounded_text(result, format_, text, *, message=None):
    if len(text.encode('utf-8')) > MAX_PREVIEW or text.count('\n') >= MAX_PREVIEW_LINES:
        result['message'] = 'Textový náhled přesahuje limit 4 MiB nebo 2000 řádků.'
    else:
        result.update(format=format_, text=text)
        if message:
            result['message'] = message


def preview(item, page=1):
    require(type(page) is int and 1 <= page <= 100, 'Invalid preview page')
    raw = item.pop('raw')
    suffix = PurePosixPath(item.pop('path')).suffix.lower()
    result = dict(item, format='unsupported', page=page)
    if len(raw) > MAX_PREVIEW:
        result['message'] = 'Soubor přesahuje limit náhledu 4 MiB.'
        return result
    if suffix == '.md':
        if not item['sidecar']:
            lines = raw.splitlines(keepends=True)
            end = next(i for i in range(1, len(lines)) if lines[i].rstrip(b'\r\n') == b'---')
            raw = b''.join(lines[end + 1:])
        try:
            text = raw.decode('utf-8')
            _bounded_text(result, 'markdown', text)
        except UnicodeError:
            result['message'] = 'Markdown není platný UTF-8.'
    elif suffix == '.json':
        try:
            text = raw.decode('utf-8')
            try:
                value = json.loads(text, object_pairs_hook=_unique_json_object)
                text = json.dumps(value, ensure_ascii=False, indent=2)
                message = 'Uložená verze · JSON je pro náhled pouze přeformátovaný.'
            except (json.JSONDecodeError, RecursionError, ValueError):
                message = ('Soubor není jednoznačný platný JSON; zobrazuje se bezpečně '
                           'jako původní text.')
            _bounded_text(result, 'json', text, message=message)
        except UnicodeError:
            result['message'] = 'JSON není platný UTF-8.'
    elif suffix in {'.html', '.htm'}:
        try:
            parser = _SafeHTMLText()
            parser.feed(raw.decode('utf-8'))
            parser.close()
            text = parser.text()
            if not text:
                result['message'] = 'HTML neobsahuje žádný zobrazitelný text.'
            else:
                _bounded_text(
                    result, 'html-text', text,
                    message='Bezpečná textová projekce HTML · původní značky ani skripty se nespouštějí.')
        except UnicodeError:
            result['message'] = 'HTML není platné UTF-8.'
    elif (suffix == '.png' and raw.startswith(b'\x89PNG\r\n\x1a\n')) or (suffix in {'.jpg', '.jpeg'} and raw.startswith(b'\xff\xd8\xff')):
        mime = 'image/png' if suffix == '.png' else 'image/jpeg'
        result.update(format='image', image='data:' + mime + ';base64,' + base64.b64encode(raw).decode())
    elif suffix == '.pdf':
        # Rasterization prevents PDF JavaScript, links and attachments reaching WebEngine.
        try:
            process = subprocess.run(['pdftoppm', '-f', str(page), '-l', str(page), '-singlefile',
                                      '-scale-to', '1200', '-png', '-'], input=raw,
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=15)
            require(process.returncode == 0 and process.stdout.startswith(b'\x89PNG')
                    and len(process.stdout) <= MAX_PREVIEW, 'PDF rendering failed')
            result.update(format='pdf', image='data:image/png;base64,' + base64.b64encode(process.stdout).decode())
        except (OSError, subprocess.TimeoutExpired, ValueError):
            result['message'] = 'Stránku PDF nelze zobrazit. Ověřte číslo stránky, soubor a instalaci poppler-utils.'
    else:
        result['message'] = 'Náhled podporuje Markdown, HTML, JSON, PNG, JPEG a PDF.'
    result.pop('sidecar', None)
    return result
