# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Reviewed same-process renderers for output composition execution."""
import base64
import hashlib
from html import escape
import json

from spikes.metadata import require


RENDERER_REVISION = 'web-static-v1'


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':')).encode()


def render_web_static(inputs, descriptor):
    """Compile ordered UTF-8 Markdown sections into a script-free bundle.

    Markdown remains text inside escaped ``pre`` elements. This deliberately
    avoids treating source HTML or Markdown extensions as executable markup.
    """
    require(descriptor['capability_id'] == 'renderer.web-static'
            and descriptor['capability_version'] == '1.0',
            'Unsupported renderer implementation')
    limit = descriptor['limits']['max_input_bytes']
    require(isinstance(inputs, list) and 0 < len(inputs)
            <= descriptor['limits']['max_sections'], 'Invalid renderer inputs')
    require(all(isinstance(item, bytes) for item in inputs),
            'Renderer inputs must be bytes')
    require(sum(map(len, inputs)) <= limit, 'Renderer input exceeds capability limit')
    sections = []
    html_sections = []
    for ordinal, raw in enumerate(inputs, 1):
        try:
            text = raw.decode('utf-8')
        except UnicodeError as exc:
            raise ValueError('Renderer input must be UTF-8 Markdown') from exc
        require('\0' not in text, 'Renderer input contains NUL')
        digest = hashlib.sha256(raw).hexdigest()
        sections.append({'ordinal': ordinal, 'sha256': digest, 'size': len(raw),
                         'content_b64': base64.b64encode(raw).decode('ascii')})
        html_sections.append(
            f'<section data-ordinal="{ordinal}"><pre>{escape(text)}</pre></section>')
    html = ('<!doctype html><html lang="cs"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>Project output preview</title></head><body><main>'
            + ''.join(html_sections) + '</main></body></html>').encode('utf-8')
    bundle = {
        'schema_version': 1,
        'format': 'static-site-bundle',
        'renderer_revision': RENDERER_REVISION,
        'sections': sections,
        'files': [{
            'path': 'index.html',
            'mime_type': 'text/html; charset=utf-8',
            'sha256': hashlib.sha256(html).hexdigest(),
            'size': len(html),
            'content_b64': base64.b64encode(html).decode('ascii'),
        }],
    }
    output = _canonical(bundle)
    require(len(output) <= descriptor['limits']['max_output_bytes'],
            'Renderer output exceeds capability limit')
    return output


REVIEWED_RENDERERS = {
    ('renderer.web-static', '1.0'): render_web_static,
}
