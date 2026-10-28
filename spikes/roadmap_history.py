# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Historical placement and non-executable prose for the migration preview."""
from collections import defaultdict
import re
from uuid import NAMESPACE_URL, uuid5

from spikes.roadmap_migration import HEADING, visible_markdown_lines

# Curated placement of this product's recorded feature IDs, not guessed
# dependencies or a change to their historical implementation/maturity state.
HISTORICAL_LANES = {
    'F-UX-SETTINGS-01': 'M1', 'FIX-MEDIA-INDEX-01': 'M1',
    'IMP-01': 'M1', 'IMP-02': 'M1', 'MOD-01': 'M6', 'MOD-01-UI': 'M6',
    'OPS-NODE-MONITOR-01': 'HARDENING', 'OPS-WEB-CONCURRENCY-01': 'HARDENING',
    'TEST-EXECUTION-01': 'HARDENING', 'V-11': 'HARDENING',
    'UX-FACELIFT-01': 'M1', 'UX-FEDERATION-02': 'M5', 'UX-MOBILE-01': 'M1',
    'UX-PROJECT-REPAIR-01': 'M1', 'UX-PROJECT-REPAIR-02': 'M1',
    'UX-UNIFIED-01': 'M1', 'UX-UNIFIED-02C': 'M1', 'UX-UNIFIED-02C-FIX1': 'M1',
    'UX-UNIFIED-02D': 'M1', 'UX-WEB-NAV-01': 'M1', 'WEB-RUNTIME-01': 'M1',
    'WF-01': 'DEV', 'WF-03': 'DEV',
}


def historical_lane(id_, hints):
    if id_ in hints:
        return hints[id_]['milestone'], 'source-dependency-annotation'
    match = re.match(r'^(?:F-)?(M[0-6])-', id_)
    if match:
        return match[1], 'source-id-milestone-namespace'
    if id_.startswith(('DOC-', 'PLAN-', 'DEV-')):
        return 'DEV', 'source-development-namespace'
    if id_.startswith('COMP-'):
        return 'M6-COMPUTE', 'source-compute-namespace'
    return HISTORICAL_LANES.get(id_), 'curated-historical-placement'


def heading_identity(title):
    match = re.match(r'(?:TODO\s+—\s+)?([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+)(?=\s|:|$)', title)
    return match[1] if match else None


def milestone_heading(scope, title):
    pattern = r'^(?:Milestone|Milník)\s+(M[0-6])(?=\s|$)' if scope == 'federated-workspace' else r'^(M\d+(?:\.\d+)?)(?=\s|$)'
    match = re.match(pattern, title, flags=re.IGNORECASE)
    if match:
        return 'MILESTONE-' + match[1].upper().replace('.', '-')
    return None


def completed_gate_evidence(value, raw):
    evidence = []
    pattern = re.compile(r'\*\*Gate (M[0-6])(?:\s*[—–:-]\s*|\s+)(?:splněn|uzavřen)\b')
    for source in value['sources']:
        if source['role'] != 'requirements':
            continue
        for line_no, _, _, line, _ in visible_markdown_lines(raw[source['key']]):
            for match in pattern.finditer(line):
                evidence.append(dict(repository_id=source['repository_id'],
                                     milestone_id='MILESTONE-' + match[1],
                                     source=source['key'], line=line_no, text=line))
    return evidence


def collect_descriptions(value, raw, nodes, checklist_owners=()):
    """Create complete Markdown notes, assigning only explicit section context.

    Unassigned notes are separate documents. No requirement becomes a task,
    and historical tasks without a recorded batch are not given a fake batch.
    """
    milestones, documents, buckets = {}, [], defaultdict(list)
    occurrences = {(item['source'], item['line']): item for item in value['occurrences']}
    for source in value['sources']:
        if source['role'] not in {'requirements', 'history', 'backlog', 'active'}:
            continue
        scope, key = source['repository_id'], source['key']
        data = raw[key]
        visible = list(visible_markdown_lines(data))
        stack, chunks, current = [], [], None
        for line_no, start, end, line, original in visible:
            heading = HEADING.match(line)
            if heading:
                if current:
                    current['end'] = start
                    chunks.append(current)
                level, title = len(heading[1]), heading[2]
                while stack and stack[-1][0] >= level:
                    stack.pop()
                stack.append((level, title))
                milestone = milestone_heading(scope, title)
                if milestone:
                    milestones[(scope, milestone)] = title
                current = dict(start=start, end=len(data), line=line_no,
                               title=title, context=[item[1] for item in stack], prose=[])
            elif line.strip():
                if current is None:
                    current = dict(start=0, end=len(data), line=1,
                                   title=source['path'], context=[], prose=[])
                occurrence = occurrences.get((key, line_no))
                # Actual task/batch/checklist rows are not generic ideas.
                # Their surrounding paragraph text is still retained in notes.
                if not occurrence:
                    current['prose'].append(line.strip())
                elif (not occurrence['id'] and occurrence['kind'] == 'checkbox'
                      and occurrence['locator'] not in checklist_owners):
                    current['prose'].append(re.sub(r'^\s*[-+*]\s+\[[ xX]\]\s*', '', line))
                elif occurrence['id'] and (scope, occurrence['id']) not in nodes:
                    current['prose'].append('Historický/zdrojový bod: ' + line.strip())
        if current:
            chunks.append(current)
        for chunk in chunks:
            if not chunk['prose']:
                continue
            owner = None
            for title in reversed(chunk['context']):
                identity = heading_identity(title)
                if identity and (scope, identity) in nodes:
                    owner = identity
                    break
                milestone = milestone_heading(scope, title)
                if milestone:
                    owner = milestone
                    break
            if owner is None and source['role'] == 'history':
                # Standalone historical ID can have a known milestone but no
                # recorded batch. Keep its text there, not a fabricated task.
                contained = [occurrences.get((key, row[0])) for row in visible
                             if chunk['start'] <= row[1] < chunk['end']]
                lanes = {historical_lane(item['id'], {})[0] for item in contained if item and item['id']}
                lanes.discard(None)
                if len(lanes) == 1:
                    owner = 'MILESTONE-' + lanes.pop()
                    milestones.setdefault((scope, owner), owner.removeprefix('MILESTONE-'))
            bucket = (scope, owner, None if owner else (key, chunk['title']))
            buckets[bucket].append(dict(source=key, **chunk,
                                       original=data[chunk['start']:chunk['end']].decode('utf-8')))
    for (scope, owner, detached_key), chunks in sorted(buckets.items(), key=lambda pair: str(pair[0])):
        identity = str(uuid5(NAMESPACE_URL, 'migration-notes:' + scope + ':' + str(owner or detached_key)))
        path = f'artifacts/{identity}/content.md'
        title = 'Volný popis — ' + (owner or chunks[0]['title'])
        body = ['# ' + title, '',
                'Podkladový text ze zdrojů; nejde o další autoritativní seznam úkolů.', '']
        for chunk in chunks:
            body += [f'## {chunk["title"]}', '',
                     f'Zdroj: {chunk["source"]}:{chunk["line"]}', '', chunk['original'], '']
        documents.append(dict(id=identity, repository_id=scope, owner_id=owner, path=path,
                              title=title, body='\n'.join(body),
                              source_sections=[dict(source=c['source'], line=c['line'],
                                                    byte_start=c['start'], byte_end=c['end']) for c in chunks],
                              prose=[text for chunk in chunks for text in chunk['prose']]))
    return milestones, documents


def description_lines(documents, scope, owner, indent):
    selected = [doc for doc in documents if doc['repository_id'] == scope and doc['owner_id'] == owner]
    lines, used = [], 0
    for doc in selected:
        # Keep complete source sections in the linked Markdown; do not truncate
        # a paragraph to fit the bounded task-graph description field.
        lines.append(' ' * indent + f'- Podklad: [{doc["title"]}]({doc["path"]})')
        for text in doc['prose']:
            text = ' '.join(text.split())
            rendered = ' ' * indent + '- Kontext: ' + text
            size = len(rendered.encode('utf-8')) + 1
            if used + size <= 4000:
                lines.append(rendered)
                used += size
    return lines
