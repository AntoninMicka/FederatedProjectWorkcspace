"""Bounded, read-only previews of committed artifact bytes; no external URLs."""
import base64
from pathlib import PurePosixPath
import subprocess

from spikes.metadata import require

MAX_PREVIEW = 4 * 1024 * 1024


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
            if text.count('\n') > 2000:
                result['message'] = 'Markdown přesahuje limit náhledu 2000 řádků.'
            else:
                result.update(format='markdown', text=text)
        except UnicodeError:
            result['message'] = 'Markdown není platný UTF-8.'
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
        result['message'] = 'Náhled podporuje Markdown, PNG, JPEG a PDF.'
    result.pop('sidecar', None)
    return result
