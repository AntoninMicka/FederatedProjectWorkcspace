# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Synthetic MON-03 preview/review using the real adapter journal, without network."""
import argparse
import json
from pathlib import Path
from uuid import uuid4

from scripts.reporting_demo import demo
from spikes.context_builder import Authority
from spikes.ollama_backend import OllamaAdapter, OllamaBinding, OllamaRuns
from spikes.project_creation import ProjectCreation
from spikes.reporting import Reporting
from spikes.reporting_proposals import ReportingProposals, PROPOSAL


def run(destination, *, confirm=False):
    result = demo(destination, llm_assistance=True)
    node = Path(result['node']); reporting = Reporting(node); project = result['project_id']
    data = reporting.read(project)
    event = next(r for r in data['records'] if r['type'] == 'Event')
    task_ref = event['value']['task_ref']
    task = next(r for r in data['records'] if r['revision_id'] == task_ref['artifact_id'])
    event_ref = reporting.pin(project, event['revision_id'])
    refs = [task['value']['scale_ref'], task['value']['execution']['context_policy'],
            *event['value']['sources'], event_ref]
    author = ProjectCreation(node).author_id()
    authority = Authority('synthetic-reporting-demo', author, str(uuid4()), 'synthetic-v1',
                          frozenset(r['artifact_id'] for r in [task_ref, *refs]))
    binding = OllamaBinding.parse(dict(schema_version=1, binding_id=str(uuid4()), revision='synthetic-v1',
        adapter='ollama', boundary='same-node', endpoint='http://127.0.0.1:11434',
        model='synthetic-offline-fixture', target_id='local-process'))
    value = dict(schema='fpw-reporting-story-v1', task_ref=task_ref, title='Návrh syntetického příběhu',
                 summary='Vazba události; nejde o ověřený provoz.', events=[event_ref], decisions=[])
    output = dict(schema=PROPOSAL, records=[dict(type='Story', entity_id=None, previous=[],
                  privacy='project', value=value)], limitations=['Syntetická odpověď; nebyl volán LLM.'])
    root = Path(destination) / 'backend'; root.mkdir(mode=0o700)
    def transport(binding, request):
        return dict(model=binding.model, done=True, response=json.dumps(output, ensure_ascii=False))
    adapter = OllamaAdapter(OllamaRuns(root), transport=transport,
                            runtime_probe=lambda binding: dict(status='unknown'))
    proposals = ReportingProposals(node, adapter)
    context = proposals.prepare(project_id=project, task_ref=task_ref, input_refs=refs,
        role='researcher', run_id=str(uuid4()), manifest_id=str(uuid4()), authority=authority, binding=binding)
    before = reporting.artifacts.workspace(project).git.head()
    proposals.dispatch(context, authority=authority, binding=binding)
    preview = proposals.preview(context, authority=authority, binding=binding)
    assert reporting.artifacts.workspace(project).git.head() == before
    result.update(preview=preview, generated_without_project_write=True)
    if confirm:
        operation = str(uuid4())
        receipt = proposals.accept(context, operation, preview['approval_digest'],
                                   authority=authority, binding=binding, confirm=True)
        replay = proposals.accept(context, operation, preview['approval_digest'],
                                  authority=authority, binding=binding, confirm=True)
        assert receipt == replay
        result.update(receipt=receipt, replay_same_receipt=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path, help='Nový neexistující adresář pro syntetický uzel')
    parser.add_argument('--confirm', action='store_true', help='Potvrdit syntetický návrh v izolovaném projektu')
    args = parser.parse_args()
    print(json.dumps(run(args.destination, confirm=args.confirm), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
