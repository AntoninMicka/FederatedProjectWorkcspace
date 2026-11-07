# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Owner-operated reporting scheduler; durable runs are not an index or a writer."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import sqlite3
import stat
import time
from uuid import uuid4
from zoneinfo import ZoneInfo

from spikes.metadata import require, uuid, validate_snapshot
from spikes.configuration import parse_node, read_config
from spikes.journal import sync_dir
from spikes.project_creation import ProjectCreation, regular
from spikes.reporting import Reporting, operation_uuid
from spikes.reporting_schema import (digest, encoded, fields, hex_id, moment,
                                    period as validate_period, ref, text)
from spikes.source_collector import SourceCollector
from spikes.storage import Git


def utc(value):
    return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def calendar_period(start_local, kind, zone, revision):
    """Calendar arithmetic precedes conversion to UTC (including DST)."""
    start = datetime.fromisoformat(start_local)
    require(start.tzinfo is not None and start.isoformat() == start.astimezone(ZoneInfo(zone)).isoformat(),
            'Explicit timezone offset required')
    if kind in {'daily', 'weekly'}:
        end_date = start.date() + timedelta(days=1 if kind == 'daily' else 7)
    else:
        require(kind in {'monthly', 'quarterly', 'annual'}, 'Custom periods require explicit manual intent')
        month = start.year * 12 + start.month - 1 + {'monthly': 1, 'quarterly': 3, 'annual': 12}[kind]
        end_date = start.date().replace(year=month // 12, month=month % 12 + 1, day=1)
    end = datetime.combine(end_date, datetime.min.time(), ZoneInfo(zone))
    result = dict(kind=kind, timezone=zone, calendar_revision=revision,
                  start_local=start.isoformat(), end_local=end.isoformat(), start_utc=utc(start), end_utc=utc(end))
    validate_period(result)
    return result


class ReportingScheduler:
    def __init__(self, node_path, *, state_dir=None, clock=time.time):
        self.reporting = Reporting(node_path)
        self.node = Path(node_path).absolute()
        require(self.node==self.node.resolve(), 'Node configuration must not use symlinks')
        regular(self.node,private=False)
        self.owner=(parse_node(read_config(self.node),location=self.node)['id'],ProjectCreation(self.node).author_id())
        self.root = Path(state_dir).absolute() if state_dir else self.node.parent / ('.' + self.node.name + '.reporting-runs')
        self._creating=not os.path.lexists(self.root)
        self.root.mkdir(mode=0o700, parents=False, exist_ok=True)
        info = self.root.lstat()
        require(self.root.resolve() == self.root and stat.S_ISDIR(info.st_mode) and
                info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700,
                'Reporting runs require owned mode 0700 without symlinks')
        require(Git(self.root).run('rev-parse','--show-toplevel',check=False).returncode!=0,
                'Run journal must be outside all Git repositories')
        self.path = self.root / 'reporting-runs.sqlite'
        require(self._creating or self.path.is_file(), 'Reporting run journal is missing; reconciliation required')
        self.clock = clock
        with self.db():
            pass
        self._creating=False
        sync_dir(self.root);sync_dir(self.root.parent)

    @contextmanager
    def db(self):
        fd = os.open(self.path, os.O_RDWR | (os.O_CREAT if self._creating else 0) | os.O_NOFOLLOW, 0o600)
        info = os.fstat(fd); os.close(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and
                info.st_nlink == 1 and not info.st_mode & 0o077, 'Unsafe reporting run journal')
        db = sqlite3.connect(self.path.as_uri()+'?mode=rw',uri=True,timeout=30)
        try:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not tables:
                require(self._creating, 'Reporting run journal has no schema; reconciliation required')
                db.execute('CREATE TABLE schema_info(version INTEGER NOT NULL,node_id TEXT NOT NULL,owner_id TEXT NOT NULL)')
                db.execute('INSERT INTO schema_info VALUES(2,?,?)',self.owner)
                db.execute('''CREATE TABLE runs(run_id TEXT PRIMARY KEY, reservation TEXT UNIQUE NOT NULL,
                    request_digest TEXT NOT NULL, document BLOB NOT NULL, candidate BLOB,
                    task_entity TEXT NOT NULL, delivery_required INTEGER NOT NULL,
                    lease_owner TEXT, lease_token TEXT, lease_until REAL)''')
                db.execute('''CREATE TABLE cutoffs(project_id TEXT NOT NULL, task_entity TEXT NOT NULL,
                    kind TEXT NOT NULL, cutoff TEXT, snapshot BLOB NOT NULL,
                    PRIMARY KEY(project_id,task_entity,kind))''')
                db.execute('CREATE TABLE watch_grants(project_id TEXT NOT NULL,watch_id TEXT NOT NULL,digest TEXT NOT NULL,PRIMARY KEY(project_id,watch_id))')
                tables={'schema_info','runs','cutoffs','watch_grants'};version=[(2,*self.owner)]
            else:
                version=db.execute('SELECT version,node_id,owner_id FROM schema_info').fetchall() if 'schema_info' in tables else []
                if tables=={'schema_info','runs','cutoffs'} and version==[(1,*self.owner)]:
                    db.execute('CREATE TABLE watch_grants(project_id TEXT NOT NULL,watch_id TEXT NOT NULL,digest TEXT NOT NULL,PRIMARY KEY(project_id,watch_id))')
                    db.execute('UPDATE schema_info SET version=2');tables.add('watch_grants');version=[(2,*self.owner)]
                require([r[1] for r in db.execute('PRAGMA table_info(runs)')] ==
                        ['run_id','reservation','request_digest','document','candidate','task_entity',
                         'delivery_required','lease_owner','lease_token','lease_until'], 'Unknown run columns')
                require([r[1] for r in db.execute('PRAGMA table_info(cutoffs)')] ==
                        ['project_id','task_entity','kind','cutoff','snapshot'], 'Unknown cutoff columns')
            base={'schema_info','runs','cutoffs','watch_grants'}
            if tables==base and version==[(2,*self.owner)]:
                db.execute('CREATE TABLE rss_bindings(key TEXT PRIMARY KEY,document BLOB NOT NULL)')
                db.execute('CREATE TABLE rss_polls(id TEXT PRIMARY KEY,binding TEXT NOT NULL,state TEXT NOT NULL,document BLOB NOT NULL,result BLOB,plan BLOB,receipt BLOB)')
                db.execute('UPDATE schema_info SET version=3')
                tables|={'rss_bindings','rss_polls'};version=[(3,*self.owner)]
            require(tables==base|{'rss_bindings','rss_polls'} and version==[(3,*self.owner)],
                    'Unknown reporting run journal schema or owner')
            require([r[1] for r in db.execute('PRAGMA table_info(rss_bindings)')]==['key','document'], 'Unknown RSS binding columns')
            require([r[1] for r in db.execute('PRAGMA table_info(rss_polls)')]==['id','binding','state','document','result','plan','receipt'], 'Unknown RSS poll columns')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def now(self):
        value = self.clock()
        require(type(value) in {int, float} and math.isfinite(value) and value >= 0, 'Invalid scheduler clock')
        return value

    def stamp(self):
        return utc(datetime.fromtimestamp(self.now(), timezone.utc))

    @staticmethod
    def _row(db, run_id):
        uuid(run_id)
        row = db.execute('SELECT document,candidate,task_entity,delivery_required,lease_owner,lease_token,lease_until,reservation '
                         'FROM runs WHERE run_id=?', (run_id,)).fetchone()
        require(row is not None, 'Unknown reporting run')
        return json.loads(row[0]), row

    @staticmethod
    def _save(db, run):
        db.execute('UPDATE runs SET document=? WHERE run_id=?', (encoded(run), run['run_id']))

    def get(self, run_id):
        with self.db() as db:
            return self._row(db, run_id)[0]

    def bind_assistance_context(self,run_id,token,context):
        """Freeze provider context in the existing FULL journal before dispatch."""
        require(isinstance(context,dict) and len(encoded(context))<=8*1024*1024,'Assistance context exceeds limit')
        with self.db() as db:
            run,row=self._row(db,run_id);self._lease(run,row,token)
            old=run.get('assistance_context')
            require(old is None or old==context,'Original assistance context cannot be replaced')
            run['assistance_context']=deepcopy(context);self._save(db,run)
        return context

    def is_correction(self,run_id):
        with self.db() as db:
            return self._row(db,run_id)[1][7].startswith('correction:')

    def grant_watch(self,project_id,watch_id,sha):
        uuid(project_id);uuid(watch_id);hex_id(sha)
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO watch_grants VALUES(?,?,?)',(project_id,watch_id,sha))

    def watch_granted(self,project_id,watch_id,sha):
        with self.db() as db:
            row=db.execute('SELECT digest FROM watch_grants WHERE project_id=? AND watch_id=?',(project_id,watch_id)).fetchone()
            return row is not None and row[0]==sha

    def preview(self, run_id):
        """Recover the exact review surface after an application restart."""
        with self.db() as db:
            run,row=self._row(db,run_id)
            request=self._candidate(run,row)
            return dict(run=run,request=request,approval_digest=digest(row[1]))

    @staticmethod
    def _candidate(run, row):
        require(row[1] is not None and run['candidate'] is not None, 'Run has no staged candidate')
        require(run['attempts'] and run['attempts'][-1]['result_sha256']==digest(row[1]),
                'Staged candidate digest changed; reconciliation required')
        return json.loads(row[1])

    def _current(self, run, delivery_required):
        request={k:run[k] for k in ('project_id','task_ref','period','rules_ref','input_head',
                                   'knowledge_cutoff','baseline_snapshot')}
        request['delivery_required']=bool(delivery_required)
        require(digest(encoded(request))==run['request_sha256'], 'Run intent digest changed')
        return self._context(request)

    def _workspace(self, project_id):
        require(self.node==self.node.resolve(), 'Node configuration must not use symlinks')
        regular(self.node,private=False)
        return self.reporting.artifacts.projects.workspace(project_id,blocking=True,deadline=time.monotonic()+60)

    def _context(self, request):
        fields(request, 'project_id task_ref period rules_ref input_head knowledge_cutoff baseline_snapshot delivery_required')
        uuid(request['project_id']); hex_id(request['input_head'], True)
        validate_period(request['period']); moment(request['knowledge_cutoff'])
        for edge in ('start','end'):
            p=request['period'];instant=moment(p[edge+'_utc'])
            require(p[edge+'_utc']==utc(instant) and
                    p[edge+'_local']==instant.astimezone(ZoneInfo(p['timezone'])).isoformat(),
                    'Scheduler period must use canonical timestamp encoding')
        require(type(request['delivery_required']) is bool, 'Invalid delivery flag')
        require(moment(request['knowledge_cutoff']) <= datetime.fromtimestamp(self.now(), timezone.utc),
                'Knowledge cutoff is in the future')
        require(moment(request['period']['end_utc']) <= datetime.fromtimestamp(self.now(), timezone.utc),
                'Reporting period has not closed')
        ws = self._workspace(request['project_id']); ws.recover()
        require(not self.root.is_relative_to(ws.git.root.resolve()), 'Run journal must be outside project Git')
        head = ws.git.head(); files = ws.git.snapshot(head); entities = validate_snapshot(files)
        require(ws.git.run('merge-base', '--is-ancestor', request['input_head'], head, check=False).returncode == 0,
                'Input head is outside project history')
        selected = [request['task_ref'], request['rules_ref']]
        if request['baseline_snapshot'] is not None:
            selected.append(request['baseline_snapshot'])
        values = []
        for pin in selected:
            ref(pin)
            require(ws.git.run('merge-base', '--is-ancestor', pin['commit_id'], request['input_head'],
                               check=False).returncode == 0, 'Input reference is newer than input head')
            raw, _ = SourceCollector.resolve(ws, request['project_id'], pin, files, entities)
            values.append(raw)
        task = json.loads(values[0])
        require(task.get('type') == 'ReportingTask', 'Expected a reporting task')
        calendar = task['value']['calendar']; p = request['period']
        require(p['timezone'] == calendar['timezone'] and p['calendar_revision'] == calendar['calendar_revision']
                and p['kind'] in calendar['periods'], 'Run calendar differs from pinned task')
        require(request['rules_ref'] == task['value']['execution']['publication_policy'],
                'Run rules differ from task publication policy')
        if request['baseline_snapshot'] is not None:
            baseline = json.loads(values[2])
            require(baseline.get('type') == 'ReportSnapshot', 'Baseline must be a report snapshot')
        return task

    @staticmethod
    def reservation(request, task):
        return digest(encoded([request['project_id'], task['entity_id'], task['revision_id'], request['period'],
                               [request['rules_ref']['artifact_id'], request['rules_ref']['sha256']]]))

    def enqueue(self, request, run_id, *, checkpoint=lambda stage: None, correction=False):
        request = deepcopy(request); uuid(run_id)
        # Validate even a replay: current access/revocation is never inferred from a run UUID.
        task = self._context(request); sha = digest(encoded(request)); key = self.reservation(request, task)
        if correction:
            require(request['baseline_snapshot'] is not None, 'Correction requires an issued predecessor')
            key = 'correction:' + digest(encoded([key, request['baseline_snapshot']['artifact_id']]))
        with self.db() as db:
            old = db.execute('SELECT run_id,request_digest,document FROM runs WHERE run_id=? OR reservation=?',
                             (run_id,key)).fetchone()
            if old:
                require(old[1] == sha, 'Period/run is already reserved with a different immutable intent')
                return json.loads(old[2])
            core = {k: v for k,v in request.items() if k != 'delivery_required'}
            run_key = digest(encoded({k: request[k] for k in
                ('project_id','task_ref','period','rules_ref','baseline_snapshot','knowledge_cutoff')}))
            run = dict(core, schema='fpw-reporting-run-v1', run_id=run_id, run_key=run_key, request_sha256=sha,
                       state='prepared', attempts=[], candidate=None, approval=None, publish_operation_id=None,
                       workspace_receipt=None, deliveries=[], last_error=None)
            db.execute('INSERT INTO runs(run_id,reservation,request_digest,document,task_entity,delivery_required) '
                       'VALUES(?,?,?,?,?,?)', (run_id,key,sha,encoded(run),task['entity_id'],int(request['delivery_required'])))
        checkpoint('run-prepared')
        return run

    def catch_up(self, project_id, task_ref, kind, start_local, *, limit=16, delivery_required=False):
        """Enqueue closed calendar periods; repeated ticks preserve their first intent."""
        require(type(limit) is int and 1 <= limit <= 128, 'Invalid catch-up limit')
        require(type(delivery_required) is bool, 'Invalid delivery flag')
        data = self.reporting.read(project_id)
        task = next((r for r in data['records'] if r['revision_id'] == task_ref['artifact_id']), None)
        require(task is not None and task['type'] == 'ReportingTask', 'Unknown reporting task')
        cal = task['value']['calendar']; start = start_local; result = []
        now = self.stamp()
        for _ in range(limit):
            p = calendar_period(start, kind, cal['timezone'], cal['calendar_revision'])
            if moment(p['end_utc']) > moment(now):
                return dict(runs=result, next_start=start, more=False)
            request = dict(project_id=project_id, task_ref=task_ref, period=p,
                rules_ref=task['value']['execution']['publication_policy'], input_head=data['commit_id'],
                knowledge_cutoff=now, baseline_snapshot=None, delivery_required=delivery_required)
            # Full current authorization and pin checks also run for cached periods.
            self._context(request)
            key = self.reservation(request, task)
            with self.db() as db:
                old = db.execute('SELECT document,delivery_required FROM runs WHERE reservation=?', (key,)).fetchone()
                require(old is None or bool(old[1])==delivery_required, 'Existing run has a different delivery requirement')
            result.append(json.loads(old[0]) if old else self.enqueue(request, str(uuid4())))
            start = p['end_local']
        p = calendar_period(start, kind, cal['timezone'], cal['calendar_revision'])
        return dict(runs=result, next_start=start, more=moment(p['end_utc']) <= moment(now))

    def claim(self, run_id, worker_id, *, lease_seconds=60):
        uuid(worker_id)
        require(type(lease_seconds) is int and 1 <= lease_seconds <= 3600, 'Invalid lease duration')
        expired = False
        with self.db() as db:
            run,row = self._row(db,run_id)
            if run['state'] == 'collecting' and row[6] <= self.now():
                run['state'] = 'unknown'; run['last_error'] = 'lease-expired'
                run['attempts'][-1].update(finished_at=self.stamp(),outcome='unknown')
                self._save(db,run); expired = True
            else:
                require(run['state'] == 'prepared', 'Run is not claimable; unknown requires reconciliation')
                # Ordered catch-up prevents a later success from silently skipping a failed period.
                history=[json.loads(raw) for (raw,) in
                         db.execute('SELECT document FROM runs WHERE task_entity=?',(row[2],))]
                completed={(r['project_id'],r['period']['kind'],r['period']['start_utc'],r['period']['end_utc'])
                           for r in history if r['state']=='completed'}
                for prior in history:
                    if prior['project_id'] == run['project_id'] and prior['period']['kind'] == run['period']['kind']:
                        covered=(prior['project_id'],prior['period']['kind'],prior['period']['start_utc'],prior['period']['end_utc'])
                        if prior['state'] in {'failed','cancelled'} and covered in completed:
                            continue
                        require(not (moment(prior['period']['start_utc']) < moment(run['period']['start_utc'])
                                     and prior['state'] != 'completed'), 'Earlier reporting period is unfinished')
                token = str(uuid4()); run['state'] = 'collecting'
                run['attempts'].append(dict(attempt_id=token,started_at=self.stamp(),finished_at=None,
                    outcome=None,input_sha256=run['request_sha256'],result_sha256=None))
                db.execute('UPDATE runs SET lease_owner=?,lease_token=?,lease_until=? WHERE run_id=?',
                           (worker_id,token,self.now()+lease_seconds,run_id));self._save(db,run)
        require(not expired, 'Expired collection lease has unknown outcome; no automatic retry')
        return dict(run=run,lease_token=token)

    def _lease(self, run, row, token):
        uuid(token)
        require(run['state']=='collecting' and row[5]==token and row[6]>self.now(), 'Stale worker lease')

    def fail(self, run_id, token, *, outcome='failed'):
        require(outcome in {'failed','cancelled','unknown'}, 'Invalid run outcome')
        with self.db() as db:
            run,row=self._row(db,run_id);self._lease(run,row,token)
            run['state']=outcome;run['last_error']=outcome
            run['attempts'][-1].update(finished_at=self.stamp(),outcome=outcome)
            self._save(db,run)
        return run

    def retry(self, run_id, *, confirm=False):
        require(confirm is True, 'Explicit retry confirmation required')
        with self.db() as db:
            run,row=self._row(db,run_id)
            require(run['state'] in {'failed','cancelled'} and run['publish_operation_id'] is None,
                    'Issued or unknown run cannot be retried; reconcile or issue a correction')
            run['state']='prepared';run['last_error']=None;run['candidate']=None;run['approval']=None
            db.execute('UPDATE runs SET candidate=NULL WHERE run_id=?',(run_id,));self._save(db,run)
        return run

    def cancel(self, run_id, *, confirm=False):
        require(confirm is True, 'Explicit cancellation confirmation required')
        with self.db() as db:
            run,_=self._row(db,run_id)
            require(run['state'] in {'prepared','review','approved'} and run['publish_operation_id'] is None,
                    'Active or issuing effect cannot be cancelled without reconciliation')
            run['state']='cancelled';run['last_error']='cancelled-by-user';self._save(db,run)
        return run

    def reconcile_no_effect(self, run_id, *, confirm=False):
        require(confirm is True, 'Human reconciliation confirmation required')
        with self.db() as db:
            run,_=self._row(db,run_id)
            require(run['state']=='unknown' and not run['deliveries'] and run['publish_operation_id'] is None,
                    'This unknown outcome needs its original effect/publication receipt')
            run['state']='failed';run['last_error']='human-confirmed-no-effect';self._save(db,run)
        return run

    def stage(self, run_id, token, request, *, checkpoint=lambda stage: None, _generation=None):
        request=deepcopy(request);fields(request,'project_id base_head records')
        require(isinstance(request['records'],list) and len(request['records'])==1, 'Expected one report publication')
        spec=request['records'][0];fields(spec,'type entity_id previous privacy value markdown')
        require(spec['type']=='ReportSnapshot' and spec['entity_id'] is None and spec['previous']==[],
                'Scheduled publication requires a fresh ReportSnapshot')
        require(isinstance(spec['markdown'],str) and len(encoded(request))<=2*1024*1024, 'Invalid candidate size')
        with self.db() as db:
            run,row=self._row(db,run_id);self._lease(run,row,token);v=spec['value']
            require(request['project_id']==run['project_id'], 'Candidate project mismatch')
            for k in ('task_ref','rules_ref','period','input_head','knowledge_cutoff','baseline_snapshot'):
                require(v[k]==run[k], 'Candidate differs from immutable run: '+k)
            self._current(run,row[3])
            require(v['corrects']==(run['baseline_snapshot'] if row[7].startswith('correction:') else None),
                    'Candidate correction differs from reserved predecessor')
            require(v['generation']['mode']=='manual' or (_generation is not None and v['generation']==_generation),
                    'Assisted report requires an application-verified generation proof')
            self.reporting.validate(request,run_id,_generation=_generation)
            run['candidate']=dict(manifest_sha256=digest(encoded(v)),markdown_sha256=digest(spec['markdown'].encode()),
                                  cache_ref='sqlite:'+run_id)
            run['state']='review'
            run['attempts'][-1].update(finished_at=self.stamp(),outcome='succeeded',result_sha256=digest(encoded(request)))
            db.execute('UPDATE runs SET candidate=? WHERE run_id=?',(encoded(request),run_id));self._save(db,run)
        checkpoint('run-review')
        return dict(run=run,approval_digest=digest(encoded(request)))

    def approve(self, run_id, approval_digest, *, confirm=False, checkpoint=lambda stage: None):
        require(confirm is True, 'Explicit human publication confirmation required')
        author=ProjectCreation(self.node).author_id()
        with self.db() as db:
            run,row=self._row(db,run_id)
            self._candidate(run,row)
            require(row[1] is not None and digest(row[1])==approval_digest, 'Candidate approval mismatch')
            if run['state'] in {'approved','issuing','issued','completed'}:
                return run
            require(run['state']=='review', 'Run is not awaiting approval')
            self._current(run,row[3])
            run['approval']=dict(decision='confirmed',actor_id=author,at=self.stamp(),policy_revision=run['rules_ref'],
                                 note='Explicit local owner approval of the exact scheduled candidate')
            run['state']='approved';self._save(db,run)
        checkpoint('run-approved')
        return run

    def publish(self, run_id, *, checkpoint=lambda stage: None, _publication_guard=lambda *args:None):
        with self.db() as db:
            run,row=self._row(db,run_id)
            if run['state'] in {'issued','completed'}:
                return run
            require(run['state'] in {'approved','issuing'}, 'Run has no approved publication intent')
            request=self._candidate(run,row)
            run['state']='issuing';run['publish_operation_id']=run_id;self._save(db,run)
            delivery=bool(row[3]);task_entity=row[2]
        checkpoint('run-issuing')
        ws=self.reporting.artifacts.workspace(run['project_id']);ws.recover()
        if ws.receipt(run_id) is None:
            self._current(run,delivery)
        # Existing writer's request digest and receipt bridge this crash boundary.
        generation=request['records'][0]['value']['generation']
        receipt=self.reporting.apply(request,run_id,confirm=True,checkpoint=checkpoint,
                                     _generation=generation if generation['mode']=='assisted' else None,
                                     _publication_guard=_publication_guard)
        checkpoint('workspace-receipt')
        pin=self.reporting.pin(run['project_id'],operation_uuid(run_id,'record:0'),receipt['commit_id'])
        with self.db() as db:
            run,_=self._row(db,run_id)
            if run['state'] in {'issued','completed'}:
                return run
            require(run['state']=='issuing', 'Publication reconciliation required')
            run['workspace_receipt']=dict(operation_id=run_id,commit_id=receipt['commit_id'],snapshot=pin)
            run['state']='issued' if delivery else 'completed'
            self._save(db,run)
            db.execute('INSERT INTO cutoffs VALUES(?,?,?,?,?) ON CONFLICT(project_id,task_entity,kind) '
                       'DO UPDATE SET snapshot=excluded.snapshot',
                       (run['project_id'],task_entity,run['period']['kind'],None,encoded(pin)))
            if not delivery:
                self._cutoff(db,run,task_entity)
        checkpoint('run-issued' if delivery else 'run-completed')
        return run

    @staticmethod
    def _cutoff(db, run, task_entity):
        old=db.execute('SELECT cutoff FROM cutoffs WHERE project_id=? AND task_entity=? AND kind=?',
                       (run['project_id'],task_entity,run['period']['kind'])).fetchone()
        cutoff=run['knowledge_cutoff']
        if old is None or old[0] is None or moment(old[0])<moment(cutoff):
            db.execute('UPDATE cutoffs SET cutoff=? WHERE project_id=? AND task_entity=? AND kind=?',
                (cutoff,run['project_id'],task_entity,run['period']['kind']))

    def begin_delivery(self, run_id, intent_sha256, *, confirm=False, checkpoint=lambda stage: None):
        require(confirm is True, 'Explicit external delivery approval required');hex_id(intent_sha256)
        with self.db() as db:
            run,_=self._row(db,run_id);require(run['state']=='issued' and not run['deliveries'],
                'Delivery already bound or unknown; automatic retry forbidden')
            run['deliveries']=[dict(delivery_id=str(uuid4()),intent_sha256=intent_sha256,
                idempotency_key=run_id,state='unknown',receipt_ref=None)]
            run['state']='unknown';run['last_error']='delivery-outcome-unknown';self._save(db,run)
        checkpoint('delivery-intent')
        return run

    def confirm_delivery(self, run_id, intent_sha256, receipt, *, confirm=False):
        require(confirm is True, 'Human/provider receipt reconciliation required');hex_id(intent_sha256)
        fields(receipt,'delivery_id idempotency_key intent_sha256 status receipt_ref')
        text(receipt['receipt_ref'])
        require(len(receipt['receipt_ref'].encode())<=4096 and receipt['status']=='delivered',
                'Expected verified node-local delivery receipt')
        with self.db() as db:
            run,row=self._row(db,run_id)
            require(run['state'] in {'unknown','completed'} and len(run['deliveries'])==1 and run['workspace_receipt'] is not None,
                    'No pending delivery to reconcile')
            delivery=run['deliveries'][0]
            require(delivery['intent_sha256']==intent_sha256==receipt['intent_sha256'] and
                    delivery['delivery_id']==receipt['delivery_id'] and receipt['idempotency_key']==run_id,
                    'Delivery receipt intent mismatch')
            if run['state']=='completed':
                require(delivery['receipt_ref']==receipt['receipt_ref'], 'Conflicting delivery receipt')
                return run
            delivery.update(state='delivered',receipt_ref=receipt['receipt_ref'])
            run['state']='completed';run['last_error']=None
            self._save(db,run);self._cutoff(db,run,row[2])
        return run

    def cutoff(self, project_id, task_entity, kind):
        uuid(project_id);uuid(task_entity)
        with self.db() as db:
            row=db.execute('SELECT cutoff,snapshot FROM cutoffs WHERE project_id=? AND task_entity=? AND kind=?',
                           (project_id,task_entity,kind)).fetchone()
            return None if row is None else dict(last_successful_cutoff=row[0],last_issued_snapshot=json.loads(row[1]))
