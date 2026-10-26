# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Validated read-only projection of roadmap feature dependencies."""
from collections import defaultdict
from hashlib import sha256
from html import escape
import json
from pathlib import Path
import re


SCHEMA = 'fpw-roadmap-graph-v1'
MAX_SOURCE = 4 * 1024 * 1024
SOURCES = ('TODO.md', 'BACKLOG.md', 'WORK_LOG.md',
           'Federovaný projektový LLM workspace – Master Checklist - základní roadmapa.md')
ID = re.compile(r'^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+$')
MILESTONE = re.compile(r'^[A-Z][A-Z0-9-]{0,31}$')


def _regular(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.resolve() != path.absolute():
        raise ValueError(f'Roadmap source is not a regular file: {path.name}')
    if path.stat().st_size > MAX_SOURCE:
        raise ValueError(f'Roadmap source is too large: {path.name}')
    return path.read_text(encoding='utf-8')


def _clean_title(value):
    value = re.sub(r'\s+', ' ', value).strip().rstrip('. ')
    value = re.sub(r'\s*\(cílová úroveň:.*$', '', value, flags=re.IGNORECASE)
    value = re.sub(r'\s+—\s+\d{4}-\d{2}-\d{2}$', '', value)
    return value.strip('* ')


def _structured_entry(text, node_id):
    quoted = re.escape(node_id)
    heading = re.search(rf'(?m)^#+\s+{quoted}\s+—\s+([^\n]+)', text)
    if heading:
        return _clean_title(heading.group(1)), None, heading.start()
    bold = re.search(
        rf'(?ms)^- \[([ x])\](?: \[([^\]]+)\])?\s+\*\*'
        rf'(?:\[([^\]]+)\]\s+)?{quoted}\s+—\s+(.+?)\*\*', text)
    if bold:
        title = _clean_title(bold.group(4))
        status = (bold.group(2) or bold.group(3) or
                  ('completed' if bold.group(1) == 'x' else 'planned')).lower()
        return title, status, bold.start()
    return None


def _entry_block(text, start):
    following = re.search(r'(?m)^(?:- \[[ x]\].*\*\*|##+\s+)', text[start + 1:])
    end = len(text) if following is None else start + 1 + following.start()
    return text[start:end]


def _catalog(source_texts, node_ids):
    result = {}
    current = re.search(r'(?m)^# TODO — ([A-Z][A-Z0-9-]+)\s*$', source_texts['TODO.md'])
    active_title = re.search(r'(?m)^Aktivní feature dávka:\s+\*\*(.+?)\*\*',
                             source_texts['TODO.md'])
    if current and active_title:
        result[current.group(1)] = {
            'title': _clean_title(active_title.group(1)), 'status': 'in progress',
            'source': 'TODO.md'}
    for node_id in node_ids:
        if node_id in result:
            continue
        for source in SOURCES[1:]:
            found = _structured_entry(source_texts[source], node_id)
            if found is None:
                continue
            title, status, start = found
            if source == 'BACKLOG.md':
                block = _entry_block(source_texts[source], start).lower()
                if re.search(r'\bodloženo\b|\bvýslovně odložil\b', block):
                    status = 'deferred'
                else:
                    status = status or 'planned'
            elif source == 'WORK_LOG.md':
                status = 'completed'
            else:
                status = status or 'planned'
            result[node_id] = {'title': title, 'status': status, 'source': source}
            break
        if node_id not in result:
            raise ValueError(f'Roadmap graph ID has no authoritative entry: {node_id}')
    return result


def _topology(nodes):
    children = defaultdict(list)
    indegree = {node_id: len(node['depends_on']) for node_id, node in nodes.items()}
    for node_id, node in nodes.items():
        for parent in node['depends_on']:
            children[parent].append(node_id)
    ready = sorted(node_id for node_id, degree in indegree.items() if degree == 0)
    order = []
    while ready:
        node_id = ready.pop(0); order.append(node_id)
        for child in sorted(children[node_id]):
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child); ready.sort()
    if len(order) != len(nodes):
        cyclic = sorted(node_id for node_id, degree in indegree.items() if degree)
        raise ValueError('Roadmap graph contains a cycle: ' + ', '.join(cyclic))
    return order, children


def _paths(nodes, order):
    paths, depths = {}, {}
    for node_id in order:
        dependencies = nodes[node_id]['depends_on']
        if not dependencies:
            paths[node_id], depths[node_id] = [node_id], 0
            continue
        parent = min(dependencies, key=lambda item: (-len(paths[item]), paths[item]))
        paths[node_id] = paths[parent] + [node_id]
        depths[node_id] = max(depths[item] for item in dependencies) + 1
    critical = min(paths.values(), key=lambda item: (-len(item), item))
    return depths, critical


class RoadmapGraph:
    def __init__(self, root=None, manifest=None):
        self.root = Path(root or Path(__file__).resolve().parents[1]).absolute()
        self.manifest = Path(manifest or self.root / 'docs' / 'roadmap-graph.json').absolute()

    def project(self):
        manifest_text = _regular(self.manifest)
        try:
            declaration = json.loads(manifest_text)
        except (json.JSONDecodeError, RecursionError) as exc:
            raise ValueError('Roadmap graph annotation is not valid JSON') from exc
        if not isinstance(declaration, dict) or set(declaration) != {'schema', 'nodes'} \
                or declaration['schema'] != SCHEMA or not isinstance(declaration['nodes'], list):
            raise ValueError('Unsupported roadmap graph annotation')
        nodes, lanes = {}, []
        for item in declaration['nodes']:
            if (not isinstance(item, dict) or set(item) != {'id', 'milestone', 'depends_on'}
                    or not isinstance(item['id'], str) or not ID.fullmatch(item['id'])
                    or not isinstance(item['milestone'], str)
                    or not MILESTONE.fullmatch(item['milestone'])
                    or not isinstance(item['depends_on'], list)
                    or any(not isinstance(value, str) or not ID.fullmatch(value)
                           for value in item['depends_on'])
                    or len(set(item['depends_on'])) != len(item['depends_on'])
                    or item['id'] in item['depends_on']):
                raise ValueError('Invalid roadmap graph node declaration')
            if item['id'] in nodes:
                raise ValueError(f'Duplicate roadmap graph ID: {item["id"]}')
            nodes[item['id']] = dict(item)
            if item['milestone'] not in lanes:
                lanes.append(item['milestone'])
        unknown = sorted({parent for node in nodes.values() for parent in node['depends_on']
                          if parent not in nodes})
        if unknown:
            raise ValueError('Unknown roadmap graph dependency: ' + ', '.join(unknown))
        order, _ = _topology(nodes)
        depths, critical = _paths(nodes, order)
        source_texts = {name: _regular(self.root / name) for name in SOURCES}
        catalog = _catalog(source_texts, nodes)
        planned = set(re.findall(
            r'(?ms)^- \[ \](?: \[planned\])?\s+\*\*(?:\[planned\]\s+)?'
            r'([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+)\s+—', source_texts['BACKLOG.md']))
        active = re.search(r'(?m)^# TODO — ([A-Z][A-Z0-9-]+)\s*$', source_texts['TODO.md'])
        required = planned | ({active.group(1)} if active else set())
        missing = sorted(required - set(nodes))
        if missing:
            raise ValueError('Roadmap feature has no graph annotation: ' + ', '.join(missing))
        complete = {node_id for node_id, item in catalog.items()
                    if item['status'] == 'completed'}
        projected = []
        for node_id in order:
            item = nodes[node_id]
            metadata = catalog[node_id]
            ready = (metadata['status'] == 'planned'
                     and all(parent in complete for parent in item['depends_on']))
            projected.append({
                'id': node_id, 'title': metadata['title'], 'status': metadata['status'],
                'source': metadata['source'], 'milestone': item['milestone'],
                'depends_on': list(item['depends_on']), 'depth': depths[node_id],
                'critical': node_id in critical, 'parallel_ready': ready})
        digest = sha256()
        for name, value in [('docs/roadmap-graph.json', manifest_text),
                            *((name, source_texts[name]) for name in SOURCES)]:
            digest.update(name.encode()); digest.update(b'\0'); digest.update(value.encode())
        return {'schema': SCHEMA, 'revision': digest.hexdigest(), 'lanes': lanes,
                'critical_path': critical,
                'parallel_ready': [item['id'] for item in projected if item['parallel_ready']],
                'nodes': projected}

    def svg(self, projection=None):
        value = projection or self.project()
        lanes = value['lanes']; nodes = value['nodes']
        by_lane = {lane: [item for item in nodes if item['milestone'] == lane]
                   for lane in lanes}
        max_depth = max((item['depth'] for item in nodes), default=0)
        lane_y, positions, y = {}, {}, 32
        for lane in lanes:
            lane_y[lane] = y
            slots = defaultdict(int)
            for item in by_lane[lane]:
                slot = slots[item['depth']]; slots[item['depth']] += 1
                positions[item['id']] = (190 + item['depth'] * 270, y + 42 + slot * 78)
            y += max(112, 62 + max(slots.values(), default=1) * 78)
        width, height = 250 + (max_depth + 1) * 270, y + 18
        parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
                 '<title id="title">Roadmapa a závislosti feature dávek</title>',
                 f'<desc id="desc">Revize {escape(value["revision"])}. Kritická cesta a paralelně připravené dávky.</desc>',
                 '<style>text{font-family:system-ui,sans-serif}.lane{fill:#f4f8fa}.lane-title{font-size:14px;font-weight:700;fill:#23465b}.edge{stroke:#93a7b3;stroke-width:2;fill:none}.node{fill:#fff;stroke:#557384;stroke-width:2}.completed{fill:#e2f3eb;stroke:#26735e}.in-progress{fill:#fff2c7;stroke:#9a6900}.deferred{fill:#eef1f3;stroke:#87939a}.critical{stroke-width:4}.ready{stroke:#176b60;stroke-dasharray:6 3}.id{font-size:12px;font-weight:700;fill:#152b38}.status{font-size:11px;fill:#4e6674}</style>']
        for lane in lanes:
            lane_height = (lane_y[lanes[lanes.index(lane) + 1]] - lane_y[lane] - 8
                           if lane != lanes[-1] else height - lane_y[lane] - 18)
            parts.append(f'<rect class="lane" x="8" y="{lane_y[lane]}" width="{width - 16}" height="{lane_height}" rx="10"/>')
            parts.append(f'<text class="lane-title" x="22" y="{lane_y[lane] + 26}">{escape(lane)}</text>')
        for item in nodes:
            x2, y2 = positions[item['id']]
            for parent in item['depends_on']:
                x1, y1 = positions[parent]
                parts.append(f'<path class="edge" d="M {x1 + 210} {y1 + 27} C {x1 + 240} {y1 + 27}, {x2 - 30} {y2 + 27}, {x2} {y2 + 27}"/>')
        for item in nodes:
            x, node_y = positions[item['id']]
            classes = ['node', item['status'].replace(' ', '-')]
            if item['critical']: classes.append('critical')
            if item['parallel_ready']: classes.append('ready')
            parts.append(f'<g><title>{escape(item["title"])}</title><rect class="{" ".join(classes)}" x="{x}" y="{node_y}" width="210" height="54" rx="9"/>')
            parts.append(f'<text class="id" x="{x + 10}" y="{node_y + 22}">{escape(item["id"])}</text>')
            parts.append(f'<text class="status" x="{x + 10}" y="{node_y + 41}">{escape(item["status"])}</text></g>')
        parts.append(f'<metadata>fpw-roadmap-graph-v1 {escape(value["revision"])}</metadata></svg>')
        return ''.join(parts)
