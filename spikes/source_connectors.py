# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Closed source connector boundary: inert items, capabilities and availability.

No connector confirms events or writes project data. Credentials and fetch
journals remain owned by the existing node-local services.
"""
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from types import SimpleNamespace
from urllib.parse import urlsplit

from spikes.metadata import require, timestamp, validate_snapshot
from spikes.public_source import project_document
from spikes.reporting_schema import PRIVACY, digest, encoded, fields, hex_id, ref, text, validate_record
from spikes.rss_reader import MAX_BYTES, MAX_ITEMS, fetch_response, checked_validators, parse_feed
from spikes.source_collector import public_url

ITEM = 'fpw-source-item-v1'
BATCH = 'fpw-source-batch-v1'
LIMITS = dict(max_wire_bytes=MAX_BYTES, max_decoded_bytes=MAX_BYTES,
              max_items=MAX_ITEMS, max_text_chars=131072, max_batch_bytes=4*1024*1024)


def utc(value):
    require(isinstance(value, str), 'Expected source timestamp')
    instant = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(instant.tzinfo is not None, 'Source timestamp needs a timezone')
    return instant.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def link(value):
    text(value)
    require(len(value) <= 8192 and not any(c.isspace() or ord(c)<32 for c in value), 'Invalid source link')
    parsed = urlsplit(value)
    require(parsed.scheme in {'http', 'https'} and parsed.hostname and not parsed.username
            and not parsed.password, 'Source link must be HTTP(S) without credentials')


@dataclass(frozen=True)
class SourceContext:
    source_id: str
    locator: str
    discovered_at: str
    privacy: str
    retention: str
    imported_at: str | None = None
    channel: str | None = None

    def validate(self):
        for value in (self.source_id, self.locator, self.retention):
            text(value); require(len(value) <= 4000, 'Source context exceeds limit')
        if self.channel is not None: text(self.channel)
        require(self.privacy in PRIVACY, 'Unknown source privacy')
        utc(self.discovered_at)
        if self.imported_at is not None: utc(self.imported_at)
        return self


def validate_item(value):
    fields(value, 'schema id connector source_id source_locator channel original_id url author title '
                 'published_at discovered_at imported_at content content_ref content_sha256 provenance privacy retention')
    require(value['schema'] == ITEM, 'Unknown source item schema')
    hex_id(value['id'])
    require(value['connector'] in CONNECTORS, 'Unknown source connector')
    for key in ('source_id', 'source_locator', 'retention'): text(value[key])
    for key in ('channel', 'original_id', 'author', 'title'):
        if value[key] is not None:
            text(value[key]); require(len(value[key]) <= 8192, 'Source field exceeds limit')
    if value['url'] is not None: link(value['url'])
    require(value['original_id'] is not None or value['url'] is not None, 'Source item needs an original identity')
    require(value['id'] == digest(encoded([value['connector'], value['source_id'], value['original_id'] or value['url']])),
            'Source item identity mismatch')
    for key in ('published_at', 'discovered_at', 'imported_at'):
        if value[key] is not None: timestamp(value[key])
    require(value['discovered_at'] is not None, 'Source discovery time is required')
    require(value['privacy'] in PRIVACY, 'Unknown source privacy')
    if value['content_ref'] is not None: ref(value['content_ref'])
    if value['content_ref'] is not None:
        require(value['content_sha256'] == value['content_ref']['sha256'], 'Source reference hash mismatch')
    if value['content'] is not None:
        require(isinstance(value['content'], str) and '\0' not in value['content']
                and len(value['content']) <= LIMITS['max_text_chars'], 'Source content exceeds limit')
        require(value['content_sha256'] == digest(value['content'].encode()), 'Source content hash mismatch')
    elif value['content_ref'] is not None:
        require(value['content_sha256'] == value['content_ref']['sha256'], 'Source reference hash mismatch')
    else:
        require(value['content_sha256'] is None, 'Missing content cannot have a content hash')
    fields(value['provenance'], 'origin raw_sha256 input_ref untrusted')
    text(value['provenance']['origin'])
    require(value['provenance']['untrusted'] is True, 'Connector items are untrusted input')
    if value['provenance']['raw_sha256'] is not None: hex_id(value['provenance']['raw_sha256'])
    if value['provenance']['input_ref'] is not None: ref(value['provenance']['input_ref'])
    return value


def item(connector, context, *, original_id, url=None, author=None, title=None,
         published_at=None, content=None, content_ref=None, raw_sha256=None, input_ref=None):
    context.validate()
    require(content is None or isinstance(content, str), 'Expected inert source text')
    original_id = original_id or None
    identity = digest(encoded([connector, context.source_id, original_id or url]))
    value = dict(schema=ITEM, id=identity, connector=connector, source_id=context.source_id,
        source_locator=context.locator, channel=context.channel, original_id=original_id, url=url,
        author=author or None, title=title or None, published_at=utc(published_at) if published_at else None,
        discovered_at=utc(context.discovered_at), imported_at=utc(context.imported_at) if context.imported_at else None,
        content=content, content_ref=deepcopy(content_ref),
        content_sha256=digest(content.encode()) if content is not None else (content_ref['sha256'] if content_ref else None),
        provenance=dict(origin=context.locator, raw_sha256=raw_sha256, input_ref=deepcopy(input_ref), untrusted=True),
        privacy=context.privacy, retention=context.retention)
    return validate_item(value)


def batch(connector, items):
    require(len(items) <= LIMITS['max_items'], 'Connector item count exceeds limit')
    for value in items:
        validate_item(value); require(value['connector'] == connector, 'Mixed connector batch')
    value = dict(schema=BATCH, connector=connector, items=items, continuation=None, not_modified=False)
    require(len(encoded(value)) <= LIMITS['max_batch_bytes'], 'Connector batch exceeds limit')
    return value


class SourceConnector:
    id = None
    name = None
    permissions = ()
    config_fields = ()
    credentials = ()
    state = 'unavailable'
    reason = 'Konektor není dostupný.'
    operations = ()

    def describe(self):
        properties = {name: {'type': 'object' if name.endswith('_ref') else 'string'} for name in self.config_fields}
        return dict(schema='fpw-source-connector-v1', id=self.id, name=self.name,
            operations=list(self.operations), config_fields=list(self.config_fields),
            config_schema=dict(type='object', properties=properties, required=list(self.config_fields), additionalProperties=False),
            permissions=list(self.permissions), credential_slots=list(self.credentials),
            credential_storage='node-local', continuation=dict(kind='none', persisted=False),
            limits=dict(LIMITS), availability=dict(state=self.state, reason=self.reason))

    def read(self, config, context, *, continuation=None):
        raise ValueError(self.reason)

    def normalize(self, payload, context):
        raise ValueError(self.reason)


class RSSConnector(SourceConnector):
    id, name = 'rss-atom', 'RSS / Atom'
    permissions, config_fields = ('public-network',), ('url',)
    state, reason, operations = 'ready', 'Přímý ruční odběr je dostupný.', ('read', 'normalize')

    def __init__(self, fetcher=None): self.fetcher = fetcher

    def describe(self):
        result=super().describe()
        if self.fetcher is None:result['continuation']=dict(kind='http-validators',persisted=False)
        return result

    def read(self, config, context, *, continuation=None):
        fields(config, 'url'); context.validate()
        require(continuation is None or (isinstance(continuation,dict) and set(continuation)=={'validators'}), 'Invalid RSS continuation')
        require(continuation is None or self.fetcher is None,'RSS continuation is unavailable for this transport')
        require(context.privacy != 'local-only', 'Local-only source cannot make network requests')
        require(config['url'] == context.locator, 'Feed URL differs from source context')
        public_url(config['url'])
        if self.fetcher is not None:return self.normalize(dict(raw=self.fetcher(config['url']),url=config['url']),context)
        response=fetch_response(config['url'],validators=checked_validators(continuation['validators'] if continuation else {}))
        result=(batch(self.id,[]) if response['status']==304 else self.normalize(dict(raw=response['raw'],url=config['url']),context))
        result.update(continuation=dict(validators=response['validators']),not_modified=response['status']==304)
        return result

    def normalize(self, payload, context):
        fields(payload, 'raw url')
        require(payload['url'] == context.locator, 'Feed URL differs from source context')
        feed = parse_feed(payload['raw'], payload['url'])
        return batch(self.id, [self.normalize_entry(e, context, feed['raw_sha256']) for e in feed['entries']])

    def normalize_entry(self, entry, context, raw_sha256=None):
        return item(self.id, context, original_id=entry['original_id'], url=entry['url'],
            author=entry['author'], title=entry['title'], published_at=entry['published_at'],
            content=entry['content'], raw_sha256=raw_sha256)


class DocumentConnector(SourceConnector):
    id, name = 'static-text', 'Stránky a dokumenty'
    config_fields = ('capture_ref',)
    permissions = ('approved-source-capture',)
    state, reason, operations = 'ready', 'Převod již zachycených HTML a textových dokumentů.', ('normalize',)

    def normalize(self, payload, context):
        fields(payload, 'raw content_type url')
        require(isinstance(payload['raw'], bytes) and len(payload['raw']) <= MAX_BYTES, 'Document exceeds limit')
        require(payload['url'] == context.locator, 'Document URL differs from source context')
        link(payload['url'])
        content, projection = project_document(payload['raw'], payload['content_type'], LIMITS['max_text_chars'])
        return batch(self.id, [item(self.id, context, original_id=payload['url'], url=payload['url'],
            title=projection['title'], content=content, raw_sha256=digest(payload['raw']))])


class SearchConnector(SourceConnector):
    id, name = 'web-search', 'Webové vyhledávání'
    config_fields = ('binding_id', 'query')
    permissions, operations = ('approved-search',), ('normalize',)
    state, reason = 'not-configured', 'Vyhledávací služba není k tomuto konektoru připojená.'

    def normalize(self, payload, context):
        require(isinstance(payload, list) and len(payload) <= MAX_ITEMS, 'Search result count exceeds limit')
        items = []
        for result in payload:
            fields(result, 'title url snippet')
            items.append(item(self.id, context, original_id=result['url'], url=result['url'],
                              title=result['title'], content=result['snippet']))
        return batch(self.id, items)


class PlatformConnector(SourceConnector):
    id, name = 'platform-channel', 'Platformní kanály (X / Twitter)'
    config_fields, credentials, permissions = ('channel',), ('api-token',), ('approved-platform-access',)
    reason = 'Připojení platformního kanálu zatím není dostupné.'


class WorkspaceOutputConnector(SourceConnector):
    id, name = 'workspace-output', 'Vydané zprávy Workspace'
    config_fields, permissions = ('project_id', 'report_ref'), ('project-read',)
    state, reason, operations = 'ready', 'Čtení připnuté vydané zprávy z oprávněného projektu.', ('read', 'normalize')

    def __init__(self, node=None, *, network=False, actor=None):
        self.node, self.network, self.actor = node, network, actor

    def describe(self):
        result = super().describe()
        if self.node is None:
            result['operations'] = ['normalize']
            result['availability'] = dict(state='not-configured', reason='Pro čtení zpráv je třeba vybrat oprávněný projekt.')
        return result

    def read(self, config, context, *, continuation=None):
        from spikes.projects import Projects
        from spikes.reporting_schema import records
        from spikes.source_collector import SourceCollector
        fields(config, 'project_id report_ref')
        context.validate()
        require(self.node is not None, 'Workspace connector requires a registered node')
        require(continuation is None, 'Workspace continuation is not implemented')
        if self.network:
            from spikes.administration import Administration
            require(self.actor is not None and Administration(self.node, deployment='web').allowed(
                self.actor, config['project_id']), 'Workspace source requires project read permission')
        git = Projects(self.node, network=self.network).repository(config['project_id'])
        head = git.head(); files = git.snapshot(head); entities = validate_snapshot(files)
        require(not self.network or all(m['privacy'] != 'local-only' for m in entities.values()), 'Project contains local-only data')
        ws = SimpleNamespace(git=git)
        raw, meta = SourceCollector.resolve(ws, config['project_id'], config['report_ref'], files, entities)
        record = validate_record(json.loads(raw))
        require(records(files, entities).get(record['revision_id']) == record, 'Expected a registered reporting record')
        require(record['type'] == 'ReportSnapshot', 'Only issued report snapshots are source outputs')
        require(PRIVACY[context.privacy] >= PRIVACY[meta['privacy']], 'Source output would relax privacy')
        markdown = record['value']['markdown']
        content_ref = ({k:v for k,v in markdown.items() if k != 'at'} |
                       dict(project_id=config['project_id'], commit_id=config['report_ref']['commit_id'])) if 'at' in markdown else markdown
        content, content_meta = SourceCollector.resolve(ws, config['project_id'], content_ref, files, entities)
        require(PRIVACY[context.privacy] >= PRIVACY[content_meta['privacy']], 'Source content would relax privacy')
        task_raw, task_meta = SourceCollector.resolve(ws, config['project_id'], record['value']['task_ref'], files, entities)
        require(PRIVACY[context.privacy] >= PRIVACY[task_meta['privacy']], 'Source task would relax privacy')
        task = validate_record(json.loads(task_raw))
        require(task['type'] == 'ReportingTask', 'Report task is unavailable')
        result = self.normalize(dict(record=record, record_ref=config['report_ref'],
                                     content=content.decode('utf-8'), content_ref=content_ref, title=task['value']['title']), context)
        require(git.head() == head, 'Project changed while reading source output')
        return result

    def normalize(self, payload, context):
        fields(payload, 'record record_ref content content_ref title')
        record = validate_record(payload['record'])
        require(record['type'] == 'ReportSnapshot', 'Only issued report snapshots are source outputs')
        require(PRIVACY[context.privacy] >= PRIVACY[record['privacy']], 'Source output would relax privacy')
        require(digest(encoded(record)) == payload['record_ref']['sha256'], 'Source record hash mismatch')
        return batch(self.id, [item(self.id, context, original_id=record['revision_id'], title=payload['title'],
            published_at=record['value']['approval']['at'], content=payload['content'], content_ref=payload['content_ref'],
            raw_sha256=payload['record_ref']['sha256'], input_ref=payload['record_ref'])])


CONNECTORS = {'rss-atom': RSSConnector, 'static-text': DocumentConnector, 'web-search': SearchConnector,
              'platform-channel': PlatformConnector, 'workspace-output': WorkspaceOutputConnector}


def connector_catalog():
    return [connector().describe() for connector in CONNECTORS.values()]
