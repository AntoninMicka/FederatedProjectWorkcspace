# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Assembled payloads are complete, scoped, reproducible and never applied."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from spikes.artifacts import Artifacts
from spikes.markdown_documents import main_todo_id
from spikes.metadata import ValidationError, validate_snapshot
from spikes.project_creation import ProjectCreation
from spikes.roadmap_bundle import assemble_bundle, digest, project_files, write_bundle
from spikes.roadmap_mapping import bind_target_preview, build_mapping
from spikes.roadmap_migration import inventory
from spikes.storage import Git
from tests.fixtures import AUTHOR
from tests.test_roadmap_mapping import MappingFixture
from tests.test_roadmap_migration import ROOT

WHEN = '2026-10-28T12:00:00Z'


class RoadmapBundleTests(MappingFixture, unittest.TestCase):
    def fixture_bundle(self, *, module=False, privacy='project'):
        source = self.fixture()
        roots = {'federated-workspace': source.root}
        modules, placements = [], []
        module_id = None
        if module:
            declaration = (ROOT/'modules/publication-experiment-registry.module.json').read_bytes()
            module_id = json.loads(declaration)['module_id']
            self.write(source, 'modules/example.module.json', declaration)
            source.commit('Module declaration')
            other = self.repository('module')
            self.write(other, 'module.json', declaration)
            self.write(other, 'ROADMAP.md', '## M1 — Modul\n\nPRIVATE MODULE DETAILS\n- [ ] Modulový směr\n')
            self.write(other, 'TODO.md', '# TODO — PER-02: Feature\n- [x] [PER-02-A] Hotový podúkol\n')
            other.commit('Module')
            roots[module_id] = other.root
            modules = [(module_id, other.root, 'HEAD')]
            placements = [dict(repository_id=module_id,batch_id='PER-02',milestone_id='MODULE-M1',
                               milestone_title='M1 — Modul',source=module_id+':ROADMAP.md',heading='## M1 — Modul')]
        value = inventory(source.root, modules=modules)
        mapping = build_mapping(value, roots, module_placements=placements)
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        base = Path(temporary.name); node = base/'node.json'
        created = ProjectCreation(node).create('Target', str(base/'target'), str(uuid4()))
        id_ = created['id']
        service = Artifacts(node)
        saved = service.save(dict(project_id=id_, artifact_id=main_todo_id(id_),
                                  base_head=created['commit_id'], title='Disposable title',
                                  body='DO NOT IMPORT THE TEST ROADMAP\n', new=True,
                                  metadata={'description':'OBSOLETE TEST LABEL','tags':['old-test']}),str(uuid4()))
        mapping = bind_target_preview(mapping,node,id_)
        operation, blobs = assemble_bundle(value,mapping,roots,author_id=AUTHOR,created_at=WHEN,privacy=privacy)
        return operation,blobs,value,mapping,roots,service,id_,saved,module_id

    def test_complete_payload_and_metadata_preserve_plan_and_exclude_test_data(self):
        op,blobs,value,mapping,roots,service,id_,saved,_ = self.fixture_bundle()
        project = op['projects'][0]
        files = project_files(project,blobs)
        entities = validate_snapshot(files)
        root = entities[main_todo_id(id_)]
        old = mapping['projects'][0]['target_preview']['original_metadata']
        for field in ('id','kind','created_at','author_id','provenance'):
            self.assertEqual(root[field],old[field])
        self.assertEqual(root['title'],'Roadmapa projektu')
        self.assertNotIn('old-test',root['tags'])
        self.assertNotIn('description',root)
        body = files[f'artifacts/{main_todo_id(id_)}/content.md'].decode()
        self.assertIn('# Roadmapa projektu',body)
        self.assertNotIn('# Migrační náhled',body)
        self.assertTrue(any(meta['kind']=='source' for meta in entities.values()))
        self.assertTrue(all(b'DO NOT IMPORT THE TEST ROADMAP' not in raw for raw in blobs.values()))
        self.assertTrue(all(b'OBSOLETE TEST LABEL' not in raw for raw in blobs.values()))
        self.assertEqual(project['expected_head'],saved['commit_id'])
        self.assertEqual(service.open(id_)['commit_id'],saved['commit_id'])
        self.assertFalse(op['import_ready']); self.assertFalse(op['project_write_performed'])
        self.assertEqual(project['deletions'],[])
        self.assertTrue(project['preserve_unlisted_entities'])
        self.assertTrue(all(entry['action']=='replace' for entry in project['files']
                            if entry['artifact_role']=='main-todo'))

    def test_fixed_context_rebuilds_identical_operation_and_exact_source_blobs(self):
        op,blobs,value,mapping,roots,*_ = self.fixture_bundle()
        self.assertEqual((op,blobs),assemble_bundle(value,mapping,roots,author_id=AUTHOR,created_at=WHEN,privacy='project'))
        for source in value['sources']:
            original = Git(roots[source['repository_id']]).run('show',source['commit_id']+':'+source['path'],binary=True).stdout
            self.assertEqual(blobs[source['sha256']],original)

    def test_module_has_own_seeded_project_uuid_root_and_private_payload(self):
        op,blobs,value,mapping,roots,service,id_,saved,module_id = self.fixture_bundle(module=True)
        main = next(p for p in op['projects'] if p['repository_id']=='federated-workspace')
        module = next(p for p in op['projects'] if p['repository_id']==module_id)
        self.assertEqual(module['mode'],'create-seeded-project')
        self.assertNotEqual(module['project_id'],id_)
        self.assertEqual(main['related_projects'][0]['project_id'],module['project_id'])
        self.assertEqual(module['location_resolution'],'required-before-create')
        self.assertEqual(module['project_metadata_proposal']['title'],'Publication & Experiment Registry')
        main_files = project_files(main,blobs); module_files = project_files(module,blobs)
        self.assertTrue(all(b'PRIVATE MODULE DETAILS' not in raw for raw in main_files.values()))
        self.assertTrue(any(b'PRIVATE MODULE DETAILS' in raw for raw in module_files.values()))
        self.assertIn(main_todo_id(module['project_id']), validate_snapshot(module_files))
        self.assertNotEqual(main['operation_id'],module['operation_id'])
        self.assertEqual(main['depends_on_operations'],[module['operation_id']])
        self.assertEqual(module['depends_on_operations'],[])
        self.assertTrue(all(entry['action']=='create' for entry in module['files']))

    def test_unbound_or_foreign_source_mapping_cannot_be_packaged(self):
        op,blobs,value,mapping,roots,*_ = self.fixture_bundle()
        mapping['projects'][0]['source_references']['foreign:secret.md']='artifacts/00000000-0000-0000-0000-000000000000/source.md'
        # Tampering cannot pass the frozen mapping binding before assembly.
        with self.assertRaisesRegex(ValidationError,'Mapping digest differs'):
            assemble_bundle(value,mapping,roots,author_id=AUTHOR,created_at=WHEN,privacy='project')

    def test_preparation_cannot_silently_relax_the_existing_main_todo_privacy(self):
        with self.assertRaisesRegex(ValidationError,'privacy would relax'):
            self.fixture_bundle(privacy='public')

    def test_package_write_is_closed_and_detects_missing_modified_extra_blobs(self):
        op,blobs,*_ = self.fixture_bundle()
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)/'package'
            write_bundle(output,op,blobs)
            self.assertEqual(json.loads((output/'operation.json').read_text()),op)
            self.assertEqual({p.name for p in (output/'blobs').iterdir()},set(blobs))
            for project in op['projects']:
                for relative, raw in project_files(project,blobs).items():
                    self.assertEqual((output/project['payload_directory']/relative).read_bytes(),raw)
            with self.assertRaises(FileExistsError): write_bundle(output,op,blobs)
            key = next(iter(blobs))
            for modified in ({k:v for k,v in blobs.items() if k!=key},dict(blobs,**{key:b'changed'}),
                             dict(blobs,**{digest(b'extra'):b'extra'})):
                with self.assertRaises(ValidationError):
                    write_bundle(Path(temporary)/'rejected',op,modified)
            self.assertFalse((Path(temporary)/'rejected').exists())
            wrong = deepcopy(op); wrong['prepared_by']=str(uuid4())
            with self.assertRaisesRegex(ValidationError,'manifest digest differs'):
                write_bundle(Path(temporary)/'wrong',wrong,blobs)
