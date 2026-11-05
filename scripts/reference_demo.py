# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Create two isolated synthetic projects and demonstrate explicit repinning."""
import argparse
import json
from pathlib import Path
import shlex
from uuid import uuid4

from spikes.artifacts import Artifacts
from spikes.configuration import parse_node, read_config
from spikes.context_builder import Authority, ContextBuilder, ProjectInput, Target
from spikes.cross_references import CrossReferences
from spikes.project_creation import ProjectCreation
from spikes.reporting_schema import digest, encoded


def demo(destination):
    destination=Path(destination).absolute()
    destination.mkdir(mode=0o700,parents=False,exist_ok=False)
    node=destination/'node.json';creator=ProjectCreation(node)
    source=creator.create('Syntetický zdroj',destination/'source',str(uuid4()))['id']
    target=creator.create('Syntetický příjemce',destination/'target',str(uuid4()))['id']
    artifacts=Artifacts(node);source_ws=artifacts.workspace(source)
    artifact_id,reference_id=str(uuid4()),str(uuid4())
    artifacts.save(dict(project_id=source,artifact_id=artifact_id,base_head=source_ws.git.head(),
        title='Syntetický podklad',body='První připnutá revize.\n',new=True),str(uuid4()))
    service=CrossReferences(node);pin=service.source_pin(source,artifact_id)
    preview=service.preview(target,reference_id,pin,'Odkaz na syntetický podklad')
    service.write(preview,str(uuid4()),digest(encoded(preview)),confirm=True)
    (destination/'01-pinned-view.json').write_bytes(encoded(service.view(target,reference_id)))
    artifacts.save(dict(project_id=source,artifact_id=artifact_id,base_head=source_ws.git.head(),
        title='Syntetický podklad',body='Druhá revize, která se sama nepřevezme.\n',new=False),str(uuid4()))
    view=service.view(target,reference_id)
    (destination/'02-newer-offered.json').write_bytes(encoded(view))
    target_ws=artifacts.workspace(target)
    authority=Authority('synthetic-reference-demo',service.user_id,parse_node(read_config(node),location=node)['id'],
                        'demo-v1',frozenset({reference_id}))
    binding=Target(str(uuid4()),'demo-v1','same-node','demo-no-model-call','none')
    builder=ContextBuilder(target_ws,target,references=service)
    context=builder.prepare(manifest_id=str(uuid4()),run_id=str(uuid4()),authority=authority,target=binding,
                            project_inputs=(ProjectInput(reference_id),))
    builder.authorize_for_dispatch(context,authority=authority,target=binding)
    (destination/'context-manifest.json').write_bytes(context.manifest_bytes)
    (destination/'context-payload.json').write_bytes(context.payload)
    update=service.preview(target,reference_id,view['newer'],'Odkaz na syntetický podklad',update=True)
    update_path=destination/'update-preview.json';update_sha=digest(encoded(update))
    update_path.write_bytes(encoded(dict(value=update,sha256=update_sha)))
    command=['python3','-m','spikes.cross_references','--node',str(node),'write',str(update_path),
             '--operation-id',str(uuid4()),'--sha256',update_sha,'--confirm']
    result=dict(node=str(node),source_project_id=source,target_project_id=target,reference_id=reference_id,
                state=view['state'],pinned_text=view['preview'].get('text'),
                explicit_update_command=shlex.join(command),note='Synthetic data only; no existing node or model was used.')
    (destination/'demo.json').write_bytes(encoded(result))
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('destination',type=Path)
    print(json.dumps(demo(parser.parse_args().destination),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
