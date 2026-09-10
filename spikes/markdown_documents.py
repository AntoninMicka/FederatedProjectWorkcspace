"""Pure Markdown projections shared by the native editor and project overview."""
import re
from uuid import UUID, uuid5

from spikes.metadata import MAX_METADATA, ValidationError, require, uuid

MAX_EDITOR = 1024 * 1024


def main_todo_id(project_id):
    uuid(project_id)
    return str(uuid5(UUID(project_id), 'federated-workspace:main-todo:v1'))


def checklist_items(body):
    """Return source offsets for list checkboxes, excluding fenced code blocks.

    The supported subset is -, + or * lists (including indented lists) and
    backtick/tilde fences. Raw HTML and links are never rendered or executed.
    """
    result, offset, fence = [], 0, None
    for line in body.splitlines(keepends=True):
        marker = re.match(r'^\s*(`{3,}|~{3,})(.*)$', line)
        if marker:
            token, tail = marker.groups()
            if fence is None:
                fence = (token[0], len(token))
            elif token[0] == fence[0] and len(token) >= fence[1] and not tail.strip():
                fence = None
        elif fence is None:
            match = re.match(r'^\s*[-+*]\s+\[([ xX])\][ \t]+(.*?)[\r\n]*$', line)
            if match:
                indent = len(line[:len(line) - len(line.lstrip(' \t'))].expandtabs(4))
                result.append(dict(offset=offset + match.start(1), indent=indent, checked=match[1].lower() == 'x',
                                   title=match[2]))
        offset += len(line)
    return result


def document(files, entities, artifact_id):
    prefix = f'artifacts/{artifact_id}/'
    entries = {p: data for p, data in files.items() if p.startswith(prefix)}
    require(entries and artifact_id in entities, 'Artifact does not exist')
    meta = entities[artifact_id]
    require(meta['kind'] == 'document', 'Only document artifacts are editable')
    sidecar = prefix + 'metadata.json'
    path = prefix + meta['file'] if sidecar in entries else next(iter(entries))
    require(path.endswith('.md'), 'Only Markdown documents are editable')
    raw = entries[path]
    require(len(raw) <= MAX_EDITOR + MAX_METADATA, 'Editor limit is 1 MiB')
    if sidecar in entries:
        body = raw.decode('utf-8')
    else:
        lines = raw.splitlines(keepends=True)
        end = next(i for i in range(1, len(lines)) if lines[i].rstrip(b'\r\n') == b'---')
        body = b''.join(lines[end + 1:]).decode('utf-8')
    require(len(body.encode()) <= MAX_EDITOR, 'Editor limit is 1 MiB')
    return dict(id=artifact_id, title=meta['title'], body=body, metadata=meta,
                path=path, sidecar=sidecar if sidecar in entries else None)


def main_todo_view(files, entities, project_id):
    """Project only safe display fields from an already validated fixed snapshot."""
    id_ = main_todo_id(project_id)
    if id_ not in entities:
        return None
    try:
        doc = document(files, entities, id_)
    except (ValidationError, UnicodeError):
        return dict(status='unsupported', items=[])
    items, ancestors = [], []
    parsed = checklist_items(doc['body'])
    for item in parsed[:1000]:
        while ancestors and ancestors[-1] >= item['indent']:
            ancestors.pop()
        items.append(dict(title=item['title'], checked=item['checked'], depth=len(ancestors)))
        ancestors.append(item['indent'])
    return dict(status='ready', title=doc['title'], items=items, total=len(parsed),
                completed=sum(item['checked'] for item in parsed), truncated=len(parsed) > len(items))
