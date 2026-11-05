# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Runnable synthetic MON-01 example in a new, isolated local node."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from spikes.artifacts import Artifacts
from spikes.project_creation import ProjectCreation
from spikes.reporting import Reporting, operation_uuid
from spikes.reporting_schema import DIMENSIONS, encoded


def demo(destination, *, llm_assistance=False):
    destination = Path(destination).absolute()
    # Never open or overwrite an existing node/project as a side effect of a demo.
    destination.mkdir(mode=0o700, parents=False, exist_ok=False)
    node = destination / 'node.json'
    receipt = ProjectCreation(node).create('Syntetická ukázka reportingu', destination / 'project', str(uuid4()))
    project_id = receipt['id']
    service = Reporting(node)
    ws = service.artifacts.workspace(project_id)
    policy_id = str(uuid4())
    Artifacts(node).save(dict(project_id=project_id, base_head=ws.git.head(), artifact_id=policy_id,
        title='Syntetická ruční policy', body='Pouze syntetická data. Ruční výběr a lidské review; bez externího účinku.',
        new=True), str(uuid4()))
    policy = service.pin(project_id, policy_id)

    def store(kind, value, *, previous=None, entity_id=None, markdown=None, confirm=False):
        operation = str(uuid4())
        spec = dict(type=kind, entity_id=entity_id, previous=previous or [], privacy='project', value=value)
        if markdown is not None:
            spec['markdown'] = markdown
        request = dict(project_id=project_id, base_head=ws.git.head(), records=[spec])
        (destination / (operation + '.request.json')).write_bytes(encoded(request))
        receipt = service.apply(request, operation, confirm=confirm)
        (destination / (operation + '.receipt.json')).write_bytes(encoded(receipt))
        return service.pin(project_id, operation_uuid(operation, 'record:0'), receipt['commit_id'])

    scale = store('EvaluationScale', dict(schema='fpw-reporting-scale-v1', title='Syntetická škála',
        comparison_policy='same-revision-only', dimensions={
            name: [dict(value=value, label=str(value), criteria='Syntetické kritérium ' + str(value))
                   for value in (['insufficient', 'low', 'medium', 'high'] if name == 'confidence' else range(6))]
            for name in DIMENSIONS}))
    scope = dict(entities=[], categories=[], geographies=[], tags=[])
    task = store('ReportingTask', dict(schema='fpw-reporting-task-v1', title='Syntetický ruční monitoring',
        goal='Předvést připnuté zdroje, událost a neměnné vydání.', scope=scope,
        source_policy=policy, selection_policy=policy, scale_ref=scale, retention_policy=policy,
        calendar=dict(timezone='Europe/Prague', calendar_revision='manual-v1', periods=['custom']),
        outputs=dict(formats=['markdown'], language='cs', required_sections=['# Přehled', '## Omezení']),
        execution=dict(llm='optional' if llm_assistance else 'disabled',
                       context_policy=policy, publication_policy=policy)))
    unknown = dict(precision='unknown', start=None, end=None, basis=[])
    sources = []
    for title, role in [('Syntetický primární zdroj', 'primary'), ('Syntetický odporující zdroj', 'secondary')]:
        sources.append(store('Source', dict(schema='fpw-reporting-source-v1', task_ref=task, title=title,
            locator='https://example.invalid/synthetic', declared_author=None, source_role=role,
            publication_date=unknown, imported_at=None, retrieved_at=None, capture_state='reference-only',
            raw_ref=None, availability='unknown', license=dict(identifier=None, terms_ref=None,
                capture_allowed=False, retention_policy=policy))))
    event = store('Event', dict(schema='fpw-reporting-event-v1', task_ref=task, title='Syntetická událost',
        summary='Dvě odporující reference; tvrzení není ověřeno.', event_date=unknown, detected_at=None,
        imported_at=None, categories=[], entities=[], geographies=[], tags=[], sources=sources,
        claims=[dict(claim_id=str(uuid4()), text='Syntetická demonstrace', scope='Pouze ukázka', stage='demonstration')],
        assessments=[], correction_reason=None))
    story = store('Story', dict(schema='fpw-reporting-story-v1', task_ref=task, title='Syntetický příběh',
        summary='Ruční vazba na událost; bez automatické deduplikace.', events=[event], decisions=[]))
    now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    snapshot = dict(schema='fpw-reporting-snapshot-v1', task_ref=task, rules_ref=policy, scale_refs=[scale],
        period=dict(kind='custom', timezone='Europe/Prague', calendar_revision='manual-v1',
            start_local='2026-01-01T00:00:00+01:00', end_local='2027-01-01T00:00:00+01:00',
            start_utc='2025-12-31T23:00:00Z', end_utc='2026-12-31T23:00:00Z'),
        knowledge_cutoff=now, input_head=ws.git.head(), baseline_snapshot=None,
        events=[event], sources=sources, stories=[story], assessments=[],
        selection=[dict(event_ref=event, reason='new')],
        query=dict(selection_policy_ref=policy, scope=scope, include_unknown_dates=True, include_late=True),
        methodology_changes=[], markdown=None,
        generation=dict(mode='manual', run_id=None, context_manifest_ref=None, result_sha256=None),
        approval=dict(decision='confirmed', actor_id=None, at=None, policy_revision=policy,
                      note='Potvrzení syntetické ukázky; žádná produkční akceptace.'),
        limitations=['Syntetická data.', 'Neznámé datum a zjištění.', 'Reference bez archivovaných bajtů.'],
        reproducibility='limited-inputs', corrects=None, correction_reason=None)
    report = store('ReportSnapshot', snapshot, confirm=True, markdown=(
        '# Přehled\n\nSyntetická demonstrace není ověřený provoz. '
        'Primární i odporující reference zůstávají připnuté.\n\n'
        '## Omezení\n\nDatum události i zjištění je neznámé. '
        'Zdroje jsou pouze reference; původní bajty nejsou archivované.\n'))
    (destination / 'report-ref.json').write_bytes(encoded(report))
    return dict(node=str(node), project_id=project_id, report=report)


def main():
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path, help='Nový neexistující adresář; rodič musí existovat')
    result = demo(parser.parse_args().destination)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
