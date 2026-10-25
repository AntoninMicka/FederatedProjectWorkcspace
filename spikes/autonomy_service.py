# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Application boundary joining governed queue steps to existing domain journals."""
import hashlib
import os
from pathlib import Path
import stat
from uuid import UUID, uuid5

from spikes.action_autonomy import (AutonomyQueue, UnknownEffect, digest,
                                     load_action_registry,
                                     parse_revision_proposal)
from spikes.backend_contract import BackendUnknown
from spikes.configuration import parse_node, read_config
from spikes.metadata import require, uuid
from spikes.project_creation import ProjectCreation
from spikes.public_source import PublicSourceUnknown
from spikes.research_workflow import load_research_profiles
from spikes.web_search import SearchUnknown


class AutonomyService:
    """Node-owner PoC; domain services remain authorities for their effects."""
    def __init__(self, node_path, projects, *, state_dir, chat_service,
                 role_workflow_service, countdown_seconds=5):
        self.node_path = Path(node_path).absolute()
        self.projects = projects
        self.chat_service = chat_service
        self.role_workflow_service = role_workflow_service
        self.registry = load_action_registry()
        self.research_profiles = load_research_profiles(self.registry)
        root = Path(state_dir).absolute()
        if not os.path.lexists(root):
            root.mkdir(mode=0o700)
        info = root.lstat()
        require(root.resolve() == root and stat.S_ISDIR(info.st_mode)
                and info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700,
                'Autonomy state directory requires owned mode 0700 without symlinks')
        self.queue = AutonomyQueue(root, self.registry, handlers={
            ('analysis.read-only', '1.0'): self._read_only,
            ('query.external', '1.0'): self._external,
            ('search.iterative-query', '1.0'): self._search,
            ('source.fetch-public', '1.0'): self._fetch_public_source,
            ('research.verify-evidence', '1.0'): self._verify_evidence,
            ('research.select-relevant', '1.0'): self._select_relevant,
            ('research.analyze', '1.0'): self._analyze_research,
            ('research.compose-report', '1.0'): self._compose_report,
            ('research.plan-next', '1.0'): self._plan_next,
            ('workflow.role-handoff', '1.0'): self._role_handoff,
            ('artifact.create-local', '1.0'): self._publish_artifact,
        }, countdown_seconds=countdown_seconds)

    def _identity(self):
        node = parse_node(read_config(self.node_path), location=self.node_path)
        return node['id'], ProjectCreation(self.node_path).author_id()

    def _owned(self, workflow_id):
        node_id, user_id = self._identity()
        return self.queue.get(workflow_id, node_id, user_id)

    @staticmethod
    def _local_only(workflow):
        return (workflow['privacy'] == 'local-only'
                or any(step['privacy'] == 'local-only'
                       for step in workflow['steps']))

    def prepare(self, plan, *, allow_local_only=True):
        require(isinstance(plan, dict), 'Autonomy plan must be an object')
        if not allow_local_only:
            require(plan.get('privacy') != 'local-only'
                    and all(isinstance(step, dict)
                            and step.get('privacy') != 'local-only'
                            for step in plan.get('steps', [])),
                    'Web autonomy does not expose local-only plans')
        workspace = self.projects.workspace(plan.get('project_id'), blocking=False)
        require(workspace.git.head() == plan.get('expected_head'),
                'Project changed before autonomy plan preparation')
        node_id, user_id = self._identity()
        return self.queue.prepare(plan, node_id, user_id)

    def replace(self, plan, *, allow_local_only=True):
        require(isinstance(plan, dict), 'Autonomy plan must be an object')
        if not allow_local_only:
            require(plan.get('privacy') != 'local-only'
                    and all(isinstance(step, dict)
                            and step.get('privacy') != 'local-only'
                            for step in plan.get('steps', [])),
                    'Web autonomy does not expose local-only plans')
        workspace = self.projects.workspace(plan.get('project_id'), blocking=False)
        require(workspace.git.head() == plan.get('expected_head'),
                'Project changed before autonomy plan replacement')
        node_id, user_id = self._identity()
        return self.queue.replace_plan(plan, node_id, user_id)

    def get(self, workflow_id, *, allow_local_only=True):
        result = self._owned(workflow_id)
        require(allow_local_only or not self._local_only(result),
                'Web autonomy does not expose local-only plans')
        return result

    def list(self, project_id=None, *, allow_local_only=True):
        node_id, user_id = self._identity()
        result = self.queue.list(node_id, user_id, project_id)
        if not allow_local_only:
            result['workflows'] = [workflow for workflow in result['workflows']
                                   if not self._local_only(workflow)]
        return result

    def attach(self, workflow_id):
        node_id, user_id = self._identity()
        return self.queue.attach_ui(workflow_id, node_id, user_id)

    def detach(self, workflow_id):
        node_id, user_id = self._identity()
        return self.queue.detach_ui(workflow_id, node_id, user_id)

    def activate(self, workflow_id, activation_digest):
        node_id, user_id = self._identity()
        return self.queue.activate(workflow_id, node_id, user_id, activation_digest)

    def approve(self, workflow_id, step_id):
        node_id, user_id = self._identity()
        return self.queue.approve(workflow_id, step_id, node_id, user_id)

    def pause(self, workflow_id):
        node_id, user_id = self._identity()
        return self.queue.pause(workflow_id, node_id, user_id)

    def resume(self, workflow_id):
        node_id, user_id = self._identity()
        return self.queue.resume(workflow_id, node_id, user_id)

    def cancel(self, workflow_id):
        node_id, user_id = self._identity()
        return self.queue.cancel(workflow_id, node_id, user_id)

    def _revision_preconditions(self, workflow, proposal):
        """Derive current preconditions from domain authorities, never the client."""
        plan = workflow['plan_revisions'][-1]['plan']
        workspace = self.projects.workspace(workflow['project_id'], blocking=False)
        available = set()
        require(workspace.git.head() == plan['expected_head'],
                'Project changed before autonomy plan revision')
        available.add('project-head-current')
        step = proposal.get('step')
        if not isinstance(step, dict):
            return available
        action = step.get('action', {}).get('id')
        value = step.get('input', {})
        if (action == 'search.iterative-query'
                and isinstance(value.get('request'), dict)
                and isinstance(value.get('preview'), dict)
                and isinstance(value.get('preview_sha256'), str)):
            candidate = self.chat_service.task_search_candidate(value['request'])
            preview = dict(candidate); preview_sha256 = preview.pop('preview_sha256', None)
            preview.pop('state', None)
            if (preview == value.get('preview')
                    and preview_sha256 == value.get('preview_sha256')):
                available.add('search-budget-current')
        elif (action == 'workflow.role-handoff'
              and isinstance(value.get('workflow_id'), str)
              and isinstance(value.get('creator_sha256'), str)):
            role = self.role_workflow_service.get(value['workflow_id'])
            creator = (role.get('steps') or [{}])[0]
            if (role.get('project_id') == workflow['project_id']
                    and creator.get('state') == 'succeeded'
                    and creator.get('response_sha256') == value.get('creator_sha256')):
                available.add('creator-result-current')
        elif action == 'source.fetch-public':
            candidate = self.chat_service.task_public_source_candidate(
                value.get('request'))
            preview = dict(candidate); preview_sha256 = preview.pop(
                'preview_sha256', None)
            preview.pop('state', None)
            if (preview == value.get('preview')
                    and preview_sha256 == value.get('preview_sha256')):
                available.add('public-source-preview-current')
        elif action == 'research.verify-evidence':
            if self._source_refs_current(value.get('source_refs'), workflow['project_id']):
                available.add('source-ledger-current')
        elif action == 'research.select-relevant':
            evidence = value.get('evidence')
            if (isinstance(evidence, dict)
                    and self._source_refs_current(evidence.get('sources'),
                                                  workflow['project_id'])):
                available.add('source-evidence-current')
        elif action in {'research.analyze', 'research.compose-report'}:
            selection = (value.get('selection') if action == 'research.analyze'
                         else {'selected_source_run_ids':
                               value.get('selected_source_run_ids')})
            if self._selection_current(selection, workflow['project_id']):
                available.add('research-selection-current')
        elif action == 'research.plan-next':
            if value.get('ledger') == self.research_ledger(workflow):
                available.add('research-ledger-current')
        return available

    def _source_refs_current(self, source_refs, project_id):
        if not isinstance(source_refs, list) or not source_refs:
            return False
        try:
            current = [self.chat_service.research_public_source(
                item.get('run_id')) for item in source_refs]
        except (AttributeError, ValueError):
            return False
        return all(item['project_id'] == project_id for item in current) and [
            item['reference'] for item in current] == source_refs

    def _selection_current(self, selection, project_id):
        if not isinstance(selection, dict):
            return False
        run_ids = selection.get('selected_source_run_ids')
        if not isinstance(run_ids, list) or not run_ids:
            return False
        try:
            sources = [self.chat_service.research_public_source(value)
                       for value in run_ids]
        except (AttributeError, ValueError):
            return False
        return all(item['project_id'] == project_id for item in sources)

    @staticmethod
    def research_ledger(workflow):
        """Project completed history to bounded immutable result references."""
        result = []
        for step in workflow.get('steps', []):
            if step.get('state') not in {'completed', 'failed', 'unknown', 'cancelled'}:
                continue
            value = step.get('result')
            result.append({'step_id': step['step_id'],
                'action_id': step['action']['id'], 'state': step['state'],
                'result_sha256': digest(value) if isinstance(value, dict) else None})
        return result

    def _candidate_option(self, action_id, privacy, value):
        descriptor = self.registry.resolve(action_id, '1.0')
        candidate = {'action': {'id': action_id, 'version': '1.0'},
            'privacy': privacy, 'cost_units': descriptor['max_cost_units'],
            'input': value}
        return {'candidate_id': digest(candidate), 'candidate': candidate}

    def _research_candidates(self, workflow, research, planner_run_id):
        """Build exact next-step options from current domain authorities."""
        allowed = {item['id'] for item in workflow['policy']['actions']}
        privacy = workflow['privacy']; candidates = []
        completed = [item for item in workflow['steps']
                     if item['state'] == 'completed']
        domain_steps = [item for item in completed
                        if item['action']['id'] != 'research.plan-next']
        last_action = domain_steps[-1]['action']['id'] if domain_steps else None
        search_steps = [item for item in completed
                        if item['action']['id'] == 'search.iterative-query']
        fetch_steps = [item for item in completed
                       if item['action']['id'] == 'source.fetch-public']
        fetched_source_ids = {item['result']['source_id'] for item in fetch_steps}

        if ('source.fetch-public' in allowed and search_steps
                and last_action in {'search.iterative-query', 'source.fetch-public'}):
            task_id = search_steps[0]['result']['task_id']
            projection = next((item for item in self.chat_service.task_outcomes(
                project_id=workflow['project_id']) if item['task_id'] == task_id), None)
            require(projection is not None,
                    'Research search result is unavailable for planning')
            search_display = projection.get('search_workflow') or {}
            rounds = search_display.get('rounds') or (
                (projection.get('outcome') or {}).get('rounds') or [])
            for round_record in rounds:
                for source in round_record.get('sources', []):
                    source_id = source.get('source_id')
                    if not isinstance(source_id, str) or source_id in fetched_source_ids:
                        continue
                    request = {'task_id': task_id,
                        'search_id': round_record['search_id'],
                        'source_id': source_id,
                        'run_id': str(uuid5(UUID(planner_run_id),
                            'fetch:' + round_record['search_id'] + ':' + source_id))}
                    context = self.chat_service.task_public_source_autonomy_candidate(
                        request)
                    preview = dict(context['preview'])
                    preview_sha256 = preview.pop('preview_sha256')
                    preview.pop('state', None)
                    candidates.append(self._candidate_option(
                        'source.fetch-public', privacy, {'request': request,
                            'preview': preview,
                            'preview_sha256': preview_sha256}))

        source_refs = [self.chat_service.public_source_reference(
            item['result']['run_id']) for item in fetch_steps]
        if (source_refs and 'research.verify-evidence' in allowed
                and last_action == 'source.fetch-public'):
            verification = {'research_id': research['research_id'],
                'source_refs': source_refs, 'ledger_sha256': digest(source_refs)}
            candidates.append(self._candidate_option(
                'research.verify-evidence', privacy, verification))

        evidence_steps = [item for item in completed
                          if item['action']['id'] == 'research.verify-evidence']
        if (evidence_steps and 'research.select-relevant' in allowed
                and last_action == 'research.verify-evidence'):
            result = evidence_steps[-1]['result']
            selection = {**research,
                'run_id': str(uuid5(UUID(planner_run_id), 'selection:run')),
                'manifest_id': str(uuid5(UUID(planner_run_id), 'selection:manifest')),
                'evidence': result['evidence'],
                'evidence_sha256': result['evidence_sha256']}
            candidates.append(self._candidate_option(
                'research.select-relevant', privacy, selection))

        selection_steps = [item for item in completed
                           if item['action']['id'] == 'research.select-relevant']
        analysis_steps = [item for item in completed
                          if item['action']['id'] == 'research.analyze']
        if selection_steps:
            selected = selection_steps[-1]['result']; selection = selected['selection']
            if ('research.analyze' in allowed
                    and last_action == 'research.select-relevant'):
                analysis = {**research,
                    'run_id': str(uuid5(UUID(planner_run_id), 'analysis:run')),
                    'manifest_id': str(uuid5(UUID(planner_run_id), 'analysis:manifest')),
                    'selection': selection,
                    'selection_sha256': selected['selection_sha256']}
                candidates.append(self._candidate_option(
                    'research.analyze', privacy, analysis))
            if ('research.compose-report' in allowed
                    and last_action in {'research.select-relevant',
                                        'research.analyze'}):
                analyzed = analysis_steps[-1]['result'] if analysis_steps else None
                task_id = search_steps[0]['result']['task_id']
                report = {**research,
                    'run_id': str(uuid5(UUID(planner_run_id), 'report:run')),
                    'manifest_id': str(uuid5(UUID(planner_run_id), 'report:manifest')),
                    'selected_source_run_ids': selection['selected_source_run_ids'],
                    'selection_sha256': selected['selection_sha256'],
                    'analysis_run_id': None if analyzed is None else analyzed['run_id'],
                    'analysis_sha256': (None if analyzed is None else
                                        analyzed['analysis_sha256']),
                    'task_id': task_id}
                candidates.append(self._candidate_option(
                    'research.compose-report', privacy, report))
        return candidates

    def propose_revision(self, proposal, *, allow_local_only=True):
        proposal = parse_revision_proposal(proposal)
        workflow = self.get(proposal.get('workflow_id'),
                            allow_local_only=allow_local_only)
        node_id, user_id = self._identity()
        return self.queue.propose_revision(proposal, node_id, user_id,
            available_preconditions=self._revision_preconditions(workflow, proposal))

    def confirm_revision(self, workflow_id, proposal_id, approval_digest, *,
                         allow_local_only=True):
        workflow = self.get(workflow_id, allow_local_only=allow_local_only)
        stored = next((item for item in workflow['revision_proposals']
                       if item['proposal_id'] == proposal_id), None)
        require(stored is not None, 'Unknown autonomy revision proposal')
        node_id, user_id = self._identity()
        return self.queue.confirm_revision(proposal_id, node_id, user_id,
            approval_digest,
            available_preconditions=self._revision_preconditions(
                workflow, stored['proposal']))

    def research_draft(self, workflow_id, step_id, *, allow_local_only=True):
        workflow = self.get(workflow_id, allow_local_only=allow_local_only)
        step = next((item for item in workflow['steps']
                     if item['step_id'] == step_id), None)
        require(step is not None
                and step['action'] == {
                    'id': 'research.compose-report', 'version': '1.0'}
                and step['state'] == 'completed'
                and isinstance(step.get('result'), dict)
                and step['result'].get('run_id') == step['input'].get('run_id')
                and step['result'].get('task_id') == step['input'].get('task_id'),
                'Completed research report step is unavailable')
        draft = self.chat_service.research_report_draft(
            step['result']['run_id'], step['result']['draft_sha256'])
        return {**draft, 'workflow_id': workflow_id, 'step_id': step_id,
                'project_id': workflow['project_id'],
                'task_id': step['result']['task_id'],
                'selected_source_run_ids': step['input'][
                    'selected_source_run_ids'],
                'analysis_run_id': step['input']['analysis_run_id']}

    def prepare_search(self, value):
        required = {'workflow_id', 'task_id', 'mode', 'countdown_seconds'}
        follow_up = required | {'parent_search_id', 'query'}
        require(isinstance(value, dict) and set(value) in (required, follow_up)
                and value['mode'] in {'manual', 'automatic'}
                and type(value['countdown_seconds']) is int
                and 3 <= value['countdown_seconds'] <= 5,
                'Invalid governed search preparation')
        uuid(value['workflow_id']); uuid(value['task_id'])
        if set(value) == follow_up:
            uuid(value['parent_search_id'])
            require(isinstance(value['query'], str), 'Invalid governed search query')
        namespace = UUID(value['workflow_id'])
        request = {'task_id': value['task_id'],
            'search_id': str(uuid5(namespace, 'initial:search')),
            'synthesis_run_id': str(uuid5(namespace, 'initial:synthesis-run')),
            'synthesis_manifest_id': str(uuid5(namespace, 'initial:synthesis-manifest'))}
        if 'query' in value:
            request.update(parent_search_id=value['parent_search_id'], query=value['query'])
        context = self.chat_service.task_search_autonomy_candidate(request)
        preview = dict(context['preview']); preview_sha256 = preview.pop('preview_sha256')
        preview.pop('state', None)
        remaining = preview['budget']['max_rounds'] - preview['round_index'] + 1
        plan = {'schema_version': 2, 'workflow_id': value['workflow_id'],
            'project_id': context['project_id'], 'expected_head': context['expected_head'],
            'mode': value['mode'], 'privacy': preview['privacy'],
            'countdown_seconds': value['countdown_seconds'],
            'continuation': {'kind': 'iterative-search-v1',
                'task_id': value['task_id'],
                'action': {'id': 'search.iterative-query', 'version': '1.0'},
                'follow_up_policy': 'first-proposed-v1'},
            'budget': {'max_steps': remaining, 'max_cost_units': remaining,
                       'max_seconds': preview['budget']['max_seconds']},
            'steps': [{'step_id': str(uuid5(namespace, 'initial:step')),
                'action': {'id': 'search.iterative-query', 'version': '1.0'},
                'privacy': preview['privacy'], 'cost_units': 1, 'depends_on': [],
                'input': {'request': request, 'preview': preview,
                          'preview_sha256': preview_sha256}}]}
        return self.prepare(plan)

    def prepare_research(self, value):
        """Prepare one reviewed research profile without dispatching its first search."""
        fields = {'workflow_id', 'task_id', 'mode', 'countdown_seconds',
                  'profile_id', 'profile_version'}
        require(isinstance(value, dict) and set(value) == fields
                and value['mode'] in {'manual', 'automatic'}
                and type(value['countdown_seconds']) is int
                and 3 <= value['countdown_seconds'] <= 5,
                'Invalid research workflow preparation')
        uuid(value['workflow_id']); uuid(value['task_id'])
        profile = self.research_profiles.get(
            (value['profile_id'], value['profile_version']))
        require(profile is not None, 'Unsupported research workflow profile')
        namespace = UUID(value['workflow_id'])
        request = {'task_id': value['task_id'],
            'search_id': str(uuid5(namespace, 'initial:search')),
            'synthesis_run_id': str(uuid5(namespace, 'initial:synthesis-run')),
            'synthesis_manifest_id': str(uuid5(
                namespace, 'initial:synthesis-manifest'))}
        context = self.chat_service.task_search_autonomy_candidate(request)
        preview = dict(context['preview'])
        preview_sha256 = preview.pop('preview_sha256'); preview.pop('state', None)
        require(preview['privacy'] in profile['privacy'],
                'Research profile does not allow task privacy')
        goal = preview['purpose']
        research = {'profile_id': profile['profile_id'],
            'profile_version': profile['version'],
            'research_id': str(uuid5(namespace, 'research')),
            'goal': goal,
            'goal_sha256': hashlib.sha256(goal.encode()).hexdigest()}
        plan = {'schema_version': 3, 'workflow_id': value['workflow_id'],
            'project_id': context['project_id'],
            'expected_head': context['expected_head'], 'mode': value['mode'],
            'privacy': preview['privacy'],
            'countdown_seconds': value['countdown_seconds'],
            'policy': {'actions': profile['actions'],
                'permissions': profile['permissions'],
                'execution_boundaries': profile['execution_boundaries'],
                'research': research},
            'budget': profile['default_budget'],
            'steps': [{'step_id': str(uuid5(namespace, 'initial:step')),
                'action': {'id': 'search.iterative-query', 'version': '1.0'},
                'privacy': preview['privacy'], 'cost_units': 1,
                'depends_on': [], 'input': {'request': request,
                    'preview': preview, 'preview_sha256': preview_sha256}}]}
        return self.prepare(plan)

    def edit_search(self, workflow_id, query):
        require(isinstance(query, str), 'Invalid governed search query')
        node_id, user_id = self._identity()
        workflow = self.queue.get(workflow_id, node_id, user_id)
        require(workflow['steps'], 'Governed search has no pending step')
        previous = workflow['steps'][-1]
        require(previous['action'] == {'id': 'search.iterative-query', 'version': '1.0'}
                and previous['state'] in {'queued', 'countdown', 'awaiting-approval'},
                'Governed search cannot be edited now')
        old_request = previous['input']['request']; round_index = previous['input'][
            'preview']['round_index']
        revision = 2 + len([item for item in workflow.get('revisions', [])
                            if item['ordinal'] == len(workflow['steps']) - 1])
        request = {'task_id': old_request['task_id'],
            'search_id': self._derived_id(workflow_id, round_index, revision, 'search'),
            'synthesis_run_id': self._derived_id(
                workflow_id, round_index, revision, 'synthesis-run'),
            'synthesis_manifest_id': self._derived_id(
                workflow_id, round_index, revision, 'synthesis-manifest')}
        parent = old_request.get('parent_search_id')
        if parent is not None:
            request.update(parent_search_id=parent, query=query)
        else:
            require(query.strip() == previous['input']['preview']['query'],
                    'The initial routed search query cannot be changed')
        context = self.chat_service.task_search_autonomy_candidate(request)
        preview = dict(context['preview']); preview_sha256 = preview.pop('preview_sha256')
        preview.pop('state', None)
        step = {'step_id': self._derived_id(workflow_id, round_index, revision, 'step'),
            'action': previous['action'], 'privacy': previous['privacy'],
            'cost_units': previous['cost_units'],
            'depends_on': previous['depends_on'],
            'input': {'request': request, 'preview': preview,
                      'preview_sha256': preview_sha256}}
        return self.queue.revise_pending_step(workflow_id, step, node_id, user_id)

    def send_now(self, workflow_id, step_id, dispatch_digest):
        node_id, user_id = self._identity()
        self.queue.send_now(workflow_id, step_id, node_id, user_id, dispatch_digest)
        return self.advance(workflow_id)

    def pause_all(self):
        self.queue.pause_all()
        return self.list()

    def resume_all(self):
        self.queue.resume_all()
        return self.list()

    def advance(self, workflow_id):
        current = self._owned(workflow_id)
        workspace = self.projects.workspace(current['project_id'], blocking=False)
        node_id, user_id = self._identity()
        result = self.queue.advance(workflow_id, node_id, user_id,
            permissions={'project-read', 'external-dispatch', 'role-dispatch',
                         'project-write'},
            allowed_privacy={'public', 'project', 'confidential', 'local-only'},
            expected_head=workspace.git.head())
        if result.get('plan_schema_version') == 3:
            result = self._append_research_planner(result, node_id, user_id)
            return self._materialize_planner(result, node_id, user_id)
        return self._append_search_continuation(result, node_id, user_id)

    def _append_research_planner(self, workflow, node_id, user_id):
        """Offer one deterministic planner revision after a completed domain action."""
        policy = workflow.get('policy') or {}; research = policy.get('research')
        steps = workflow.get('steps') or []
        if (not isinstance(research, dict) or not steps
                or any(item.get('state') not in {'completed', 'cancelled'}
                       for item in steps)
                or steps[-1].get('state') != 'completed'
                or steps[-1].get('action') == {
                    'id': 'research.plan-next', 'version': '1.0'}
                or any(item.get('state') == 'pending'
                       for item in workflow.get('revision_proposals', []))):
            return workflow
        profile = self.research_profiles.get(
            (research['profile_id'], research['profile_version']))
        require(profile is not None, 'Research workflow profile is unavailable')
        planner_cost = 2; budget = dict(workflow['budget'])
        maximum = profile['maximum_budget']; last = steps[-1]
        budget['max_steps'] = max(budget['max_steps'], len(steps) + 1)
        budget['max_cost_units'] = max(
            budget['max_cost_units'], workflow['spent_cost'] + planner_cost)
        if workflow['remaining_seconds'] == 0:
            budget['max_seconds'] = min(
                maximum['max_seconds'], budget['max_seconds'] + 300)
        if any(budget[key] > maximum[key] for key in budget):
            proposal_id = str(uuid5(UUID(workflow['workflow_id']),
                'research-planner:' + last['step_id'] + ':budget-finish'))
            proposal = {'schema_version': 1, 'proposal_id': proposal_id,
                'workflow_id': workflow['workflow_id'],
                'base_revision': workflow['plan_revision'],
                'base_plan_digest': workflow['plan_revisions'][-1]['plan_digest'],
                'kind': 'finish',
                'reason': 'The reviewed research profile maximum is exhausted.',
                'step': None, 'repeat_of': None,
                'budget': dict(workflow['budget'])}
            return self.queue.propose_revision(proposal, node_id, user_id,
                available_preconditions=self._revision_preconditions(
                    workflow, proposal))
        ledger = self.research_ledger(workflow); ledger_sha = digest(ledger)
        marker = 'research-planner:' + last['step_id'] + ':' + ledger_sha
        planner_input = {**research,
            'run_id': str(uuid5(UUID(workflow['workflow_id']), marker + ':run')),
            'manifest_id': str(uuid5(
                UUID(workflow['workflow_id']), marker + ':manifest')),
            'plan_revision': workflow['plan_revision'] + 1,
            'ledger': ledger, 'ledger_sha256': ledger_sha,
            'remaining_budget': {
                'max_steps': max(0, budget['max_steps'] - len(steps) - 1),
                'max_cost_units': max(
                    0, budget['max_cost_units'] - workflow['spent_cost']
                    - planner_cost),
                'max_seconds': workflow['remaining_seconds']}}
        planner_input['available_candidates'] = self._research_candidates(
            workflow, research, planner_input['run_id'])
        step = {'step_id': str(uuid5(
            UUID(workflow['workflow_id']), marker + ':step')),
            'action': {'id': 'research.plan-next', 'version': '1.0'},
            'privacy': last['privacy'], 'cost_units': planner_cost,
            'depends_on': [last['step_id']], 'input': planner_input}
        proposal = {'schema_version': 1,
            'proposal_id': str(uuid5(
                UUID(workflow['workflow_id']), marker + ':revision')),
            'workflow_id': workflow['workflow_id'],
            'base_revision': workflow['plan_revision'],
            'base_plan_digest': workflow['plan_revisions'][-1]['plan_digest'],
            'kind': 'append',
            'reason': 'Review the completed domain result and propose the next bounded action.',
            'step': step, 'repeat_of': None, 'budget': budget}
        return self.queue.propose_revision(proposal, node_id, user_id,
            available_preconditions=self._revision_preconditions(workflow, proposal))

    def _materialize_planner(self, workflow, node_id, user_id):
        steps = workflow.get('steps') or []
        if not steps or steps[-1].get('state') != 'completed' or steps[-1].get(
                'action') != {'id': 'research.plan-next', 'version': '1.0'}:
            return workflow
        planner = steps[-1]; result = planner.get('result')
        require(isinstance(result, dict), 'Research planner result is unavailable')
        profile_key = (planner['input']['profile_id'],
                       planner['input']['profile_version'])
        profile = self.research_profiles.get(profile_key)
        require(profile is not None, 'Research planner profile is unavailable')
        profile_actions = {item['id'] for item in profile['actions']}
        kind = result['decision']; step = repeat_of = None
        if kind in {'append', 'repeat'}:
            candidate = result['candidate']
            require(any(item['candidate_id'] == digest(candidate)
                        and item['candidate'] == candidate
                        for item in planner['input'].get(
                            'available_candidates', [])),
                    'Research planner selected an unavailable candidate')
            require(candidate['action']['id'] in profile_actions,
                    'Research planner proposed an action outside its profile')
            repeat_of = result['repeat_step_id'] if kind == 'repeat' else None
            dependency = repeat_of or planner['step_id']
            step_id = str(uuid5(UUID(workflow['workflow_id']),
                'research-planner:' + result['run_id'] + ':'
                + result['proposal_sha256'] + ':step'))
            step = {'step_id': step_id, 'action': candidate['action'],
                'privacy': candidate['privacy'],
                'cost_units': candidate['cost_units'],
                'depends_on': [dependency], 'input': candidate['input']}
        budget = dict(workflow['budget'])
        maximum = profile['maximum_budget']
        if step is not None:
            budget['max_steps'] = max(budget['max_steps'], len(steps) + 1)
            spent = budget['max_cost_units'] - workflow['remaining_cost']
            budget['max_cost_units'] = max(budget['max_cost_units'],
                                           spent + step['cost_units'])
            if workflow['remaining_seconds'] == 0:
                budget['max_seconds'] = min(maximum['max_seconds'],
                                             budget['max_seconds'] + 300)
        require(all(budget[key] <= maximum[key] for key in budget),
                'Research planner proposal exceeds the profile maximum')
        proposal_id = str(uuid5(UUID(workflow['workflow_id']),
            'research-planner:' + result['run_id'] + ':'
            + result['proposal_sha256'] + ':revision'))
        reason = result['reason']
        if kind == 'finish':
            reason += ' [' + result['finish_reason'] + ']'
        proposal = {'schema_version': 1, 'proposal_id': proposal_id,
            'workflow_id': workflow['workflow_id'],
            'base_revision': workflow['plan_revision'],
            'base_plan_digest': workflow['plan_revisions'][-1]['plan_digest'],
            'kind': kind, 'reason': reason, 'step': step,
            'repeat_of': repeat_of, 'budget': budget}
        return self.queue.propose_revision(proposal, node_id, user_id,
            available_preconditions=self._revision_preconditions(workflow, proposal))

    @staticmethod
    def _read_only(value, execution):
        return {'schema_version': 1, 'kind': 'read-only-analysis-reference',
                'project_id': execution['project_id'],
                'project_commit': execution['expected_head'],
                'selection_sha256': value['selection_sha256']}

    def _external(self, value, execution):
        require(value['privacy'] == 'public',
                'Autonomous external action only accepts public input')
        try:
            self.chat_service.external_confirm({
                'approval_id': value['approval_id'],
                'preview_sha256': value['preview_sha256'],
                'approved': True, 'privacy': value['privacy']})
        except BackendUnknown as exc:
            raise UnknownEffect(str(exc)) from exc
        return {'schema_version': 1, 'kind': 'external-result-reference',
                'approval_id': value['approval_id'], 'state': 'recorded'}

    def _search(self, value, execution):
        require(set(value) == {'request', 'preview', 'preview_sha256'}
                and isinstance(value['request'], dict)
                and isinstance(value['preview'], dict)
                and isinstance(value['preview_sha256'], str),
                'Invalid iterative search autonomy input')
        candidate = self.chat_service.task_search_candidate(value['request'])
        candidate_preview = dict(candidate)
        candidate_sha = candidate_preview.pop('preview_sha256', None)
        candidate_preview.pop('state', None)
        require(candidate_preview == value['preview']
                and candidate_sha == value['preview_sha256'],
                'Iterative search preview changed before dispatch')
        prepared = self.chat_service.task_search_preview(value['request'])
        require(prepared['preview_sha256'] == value['preview_sha256'],
                'Iterative search preview changed while preparing dispatch')
        try:
            projection = self.chat_service.task_search_confirm({
                'task_id': value['request']['task_id'],
                'search_id': value['request']['search_id'],
                'preview_sha256': value['preview_sha256'], 'approved': True})
        except (BackendUnknown, SearchUnknown) as exc:
            raise UnknownEffect(str(exc)) from exc
        workflow = projection.get('search_workflow') or {}
        next_queries = workflow.get('next_queries') or []
        rounds = workflow.get('rounds') or []
        return {'schema_version': 1, 'kind': 'iterative-search-reference',
                'task_id': value['request']['task_id'],
                'search_id': value['request']['search_id'],
                'preview_sha256': value['preview_sha256'],
                'state': projection['state'],
                'round_index': (rounds[-1]['round_index'] if rounds else
                                value['preview']['round_index']),
                'next_query': next_queries[0] if next_queries else None}

    def _fetch_public_source(self, value, execution):
        request = value['request']
        candidate = self.chat_service.task_public_source_candidate(request)
        candidate_preview = dict(candidate)
        candidate_sha = candidate_preview.pop('preview_sha256', None)
        candidate_preview.pop('state', None)
        require(candidate_preview == value['preview']
                and candidate_sha == value['preview_sha256'],
                'Public source preview changed before dispatch')
        prepared = self.chat_service.task_public_source_preview(request)
        require(prepared['preview_sha256'] == value['preview_sha256'],
                'Public source preview changed while preparing dispatch')
        try:
            self.chat_service.task_public_source_confirm({**request,
                'preview_sha256': value['preview_sha256'], 'approved': True})
        except PublicSourceUnknown as exc:
            raise UnknownEffect(str(exc)) from exc
        reference = self.chat_service.task_public_source_reference(
            {'task_id': request['task_id'], 'run_id': request['run_id']})
        require(reference['search_id'] == request['search_id']
                and reference['source_id'] == request['source_id'],
                'Public source result differs from the approved request')
        return {'schema_version': 1, 'kind': 'public-source-reference',
            'task_id': reference['task_id'], 'search_id': reference['search_id'],
            'source_id': reference['source_id'], 'run_id': reference['run_id'],
            'state': 'succeeded', 'raw_sha256': reference['raw_sha256'],
            'text_sha256': reference['text_sha256'],
            'projection_sha256': reference['projection_sha256'],
            'final_url': reference['url']}

    def _verify_evidence(self, value, execution):
        require(self._source_refs_current(value['source_refs'],
                                          execution['project_id']),
                'Research source ledger changed before verification')
        relations = []
        sources = value['source_refs']
        for index, left in enumerate(sources):
            for right in sources[index + 1:]:
                if len(relations) >= 128:
                    break
                if left['origin'] == right['origin']:
                    relations.append({'kind': 'same-origin',
                        'source_run_ids': [left['run_id'], right['run_id']],
                        'observation': 'Both fetched URLs have the same canonical origin.'})
                if (len(relations) < 128
                        and left['raw_sha256'] == right['raw_sha256']):
                    relations.append({'kind': 'same-content',
                        'source_run_ids': [left['run_id'], right['run_id']],
                        'observation': 'Both reader runs have the same raw content digest.'})
        warnings = ([] if len(sources) > 1 else
                    ['Only one fetched source is available; independence is not established.'])
        evidence = {'sources': sources, 'relations': relations,
                    'warnings': warnings}
        return {'schema_version': 1, 'kind': 'research-evidence',
            'research_id': value['research_id'], 'evidence': evidence,
            'evidence_sha256': digest(evidence)}

    def _research_model(self, action_id, value, execution):
        try:
            return self.chat_service.research_model_action(
                action_id, value, execution)
        except BackendUnknown as exc:
            raise UnknownEffect(str(exc)) from exc

    def _select_relevant(self, value, execution):
        require(self._source_refs_current(value['evidence']['sources'],
                                          execution['project_id']),
                'Research evidence changed before selection')
        return self._research_model('research.select-relevant', value, execution)

    def _analyze_research(self, value, execution):
        require(self._selection_current(value['selection'], execution['project_id']),
                'Research selection changed before analysis')
        return self._research_model('research.analyze', value, execution)

    def _compose_report(self, value, execution):
        require(self._selection_current({'selected_source_run_ids':
            value['selected_source_run_ids']}, execution['project_id']),
            'Research selection changed before report composition')
        return self._research_model('research.compose-report', value, execution)

    def _plan_next(self, value, execution):
        workflow = self._owned(execution['workflow_id'])
        require(value['plan_revision'] == workflow['plan_revision']
                and value['ledger'] == self.research_ledger(workflow),
                'Research planner input is stale')
        return self._research_model('research.plan-next', value, execution)

    @staticmethod
    def _derived_id(workflow_id, round_index, revision, label):
        return str(uuid5(UUID(workflow_id),
                         f'iterative-search:{round_index}:{revision}:{label}'))

    def _append_search_continuation(self, workflow, node_id, user_id):
        if workflow.get('state') not in {'queued', 'paused'}:
            return workflow
        steps = workflow.get('steps') or []
        if not steps or steps[-1]['action'] != {
                'id': 'search.iterative-query', 'version': '1.0'}:
            return workflow
        result = steps[-1].get('result')
        if steps[-1].get('state') != 'completed' or not isinstance(result, dict):
            return workflow
        query = result.get('next_query')
        if query is None:
            return workflow
        round_index = result['round_index'] + 1; revision = 1
        request = {'task_id': result['task_id'],
            'search_id': self._derived_id(workflow['workflow_id'], round_index,
                                          revision, 'search'),
            'synthesis_run_id': self._derived_id(workflow['workflow_id'], round_index,
                                                 revision, 'synthesis-run'),
            'synthesis_manifest_id': self._derived_id(
                workflow['workflow_id'], round_index, revision, 'synthesis-manifest'),
            'parent_search_id': result['search_id'], 'query': query}
        candidate = self.chat_service.task_search_candidate(request)
        preview = dict(candidate); preview_sha256 = preview.pop('preview_sha256')
        preview.pop('state', None)
        step = {'step_id': self._derived_id(workflow['workflow_id'], round_index,
                                            revision, 'step'),
                'action': {'id': 'search.iterative-query', 'version': '1.0'},
                'privacy': preview['privacy'], 'cost_units': 1,
                'depends_on': [steps[-1]['step_id']],
                'input': {'request': request, 'preview': preview,
                          'preview_sha256': preview_sha256}}
        return self.queue.append_step(workflow['workflow_id'], step, node_id, user_id)

    def _role_handoff(self, value, execution):
        uuid(value['workflow_id'])
        require(isinstance(value['creator_sha256'], str)
                and len(value['creator_sha256']) == 64,
                'Invalid creator result digest')
        workflow = self.role_workflow_service.get(value['workflow_id'])
        require(workflow['project_id'] == execution['project_id'],
                'Role workflow belongs to a different project')
        creator = workflow['steps'][0]
        require(creator['state'] == 'succeeded'
                and creator['response_sha256'] == value['creator_sha256'],
                'Creator result differs from autonomy handoff')
        prepared = self.role_workflow_service.prepare_opponent(value['workflow_id'])
        opponent = prepared['steps'][1]
        return {'schema_version': 1, 'kind': 'role-handoff-reference',
                'workflow_id': value['workflow_id'],
                'step_id': opponent['step_id'], 'state': opponent['state'],
                'approval_digest': opponent['approval_digest']}

    def _publish_artifact(self, value, execution):
        request = value['request']
        required = {'workflow_id', 'step_id', 'result_sha256', 'project_id',
                    'expected_head', 'artifact_id', 'title', 'created_at', 'operation_id'}
        require(set(request) == required, 'Invalid autonomy publication request')
        require(request['project_id'] == execution['project_id']
                and request['expected_head'] == execution['expected_head'],
                'Autonomy publication project or HEAD differs')
        require(value['target'] == 'artifact:' + request['artifact_id']
                and value['content_type'] == 'text/markdown'
                and value['content_sha256'] == request['result_sha256'],
                'Autonomy publication output differs from exact approval')
        require(value['provenance'] == {'workflow_id': request['workflow_id'],
                                        'step_id': request['step_id']},
                'Autonomy publication provenance differs')
        result = self.role_workflow_service.publish(request)
        return {'schema_version': 1, 'kind': 'local-artifact-reference',
                'project_id': request['project_id'],
                'artifact_id': request['artifact_id'],
                'commit_id': result['commit_id'],
                'receipt_sha256': digest(result)}
