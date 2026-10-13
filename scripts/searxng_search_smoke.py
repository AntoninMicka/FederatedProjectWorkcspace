#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Isolated live SearXNG -> Context Manifest -> Ollama smoke."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spikes.chat_service import ChatService
from spikes.projects import Projects
from spikes.storage import Git
from spikes.task_outcomes import TaskOutcomes


def write_json(path, value, mode):
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True) + '\n')
    path.chmod(mode)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--searxng-endpoint', default='http://127.0.0.1:8888')
    parser.add_argument('--ollama-endpoint', default='http://127.0.0.1:11434')
    parser.add_argument('--model', default='gemma4:latest')
    parser.add_argument('--query', default='SearXNG official documentation')
    parser.add_argument('--route-through-model', action='store_true',
                        help='Ask the configured Ollama task router to produce web-search.')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='fpw-search-smoke-') as temporary:
        base = Path(temporary); project_root = base / 'project'; project_root.mkdir(mode=0o700)
        project_state = base / 'project-state'; project_state.mkdir(mode=0o700)
        chat_state = base / 'chat-state'; chat_state.mkdir(mode=0o700)
        project_id, author_id, node_id = str(uuid4()), str(uuid4()), str(uuid4())
        write_json(project_root / 'project.json', {'schema_version': 1, 'id': project_id,
            'title': 'SearXNG smoke', 'created_at': '2026-10-12T00:00:00Z',
            'author_id': author_id}, 0o600)
        git = Git(project_root); git.run('init', '--initial-branch=main')
        (project_root / '.git').chmod(0o700)
        git.commit('Project')
        node_path = base / 'node.json'
        write_json(node_path, {'schema_version': 1, 'id': node_id, 'name': 'Smoke node',
            'projects': [{'project_id': project_id, 'root': str(project_root),
                          'state_dir': str(project_state)}]}, 0o600)
        service = ChatService(node_path, Projects(node_path), state_dir=chat_state)
        service.configure({'schema_version': 1, 'binding_id': str(uuid4()),
            'revision': 'live-smoke', 'adapter': 'ollama', 'boundary': 'same-node',
            'endpoint': args.ollama_endpoint, 'model': args.model,
            'target_id': 'local-process'})
        service.configure_search({'schema_version': 1, 'binding_id': str(uuid4()),
            'revision': 'live-smoke', 'adapter': 'searxng', 'boundary': 'same-node',
            'endpoint': args.searxng_endpoint, 'target_id': 'local-process',
            'result_limit': 3, 'timeout_seconds': 15})
        task_id, thread_id, message_id = str(uuid4()), str(uuid4()), str(uuid4())
        request = {'task_id': task_id, 'project_id': project_id,
            'expected_head': git.head(), 'thread_id': thread_id, 'message_id': message_id,
            'run_id': str(uuid4()), 'manifest_id': str(uuid4()),
            'selected_message_ids': [], 'selected_artifact_ids': [],
            'content': args.query, 'privacy': 'project',
            'created_at': '2026-10-12T00:00:00Z',
            'run_choice': {'mode': 'orchestration', 'adapter': 'ollama', 'model': None}}
        outcome = {'schema_version': 1, 'kind': 'web-search',
            'purpose': 'Live integration smoke', 'query': args.query,
            'message_ids': [message_id], 'artifact_ids': []}
        if args.route_through_model:
            routed = service.task_route(request)
            if routed['outcome']['kind'] != 'web-search':
                raise RuntimeError('Task router did not select web-search')
        else:
            node_owner, user_owner = service._identity()
            TaskOutcomes(chat_state).prepare(node_id=node_owner, user_id=user_owner,
                request=request, routed={'task_id': task_id, 'outcome': outcome,
                    'privacy': 'project', 'project_commit': git.head(),
                    'run_id': request['run_id'], 'manifest_id': request['manifest_id']})
        preview = service.task_search_preview({'task_id': task_id,
            'search_id': str(uuid4()), 'synthesis_run_id': str(uuid4()),
            'synthesis_manifest_id': str(uuid4())})
        projection = service.task_search_confirm({'task_id': task_id,
            'search_id': preview['search_id'], 'preview_sha256': preview['preview_sha256'],
            'approved': True})
        result = projection['outcome']
        print(json.dumps({'state': projection['state'], 'kind': result['kind'],
            'query': result['query'], 'sources': len(result['sources']),
            'answer_chars': len(result['content']), 'model': result['model'],
            'search_id': result['search_id'], 'run_id': result['run_id']},
            ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
