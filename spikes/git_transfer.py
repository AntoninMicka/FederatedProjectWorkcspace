# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Native Git initial transfer, public history only, without hooks or merge."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import sys
import tempfile

from spikes.administration import Administration, identifier
from spikes.configuration import committed_project
from spikes.federation_probe import check_peer
from spikes.journal import sync_dir
from spikes.lxc_setup import ACTOR
from spikes.metadata import require, validate_snapshot
from spikes.projects import Projects
from spikes.project_creation import ProjectCreation
from spikes.storage import Git

MAX_BUNDLE = 64 * 1024 * 1024


def git_run(git, *args, **kwargs):
    return git.run(*args, env_extra={'GIT_NO_REPLACE_OBJECTS': '1'}, **kwargs)


def validate_history(git, head, project_id):
    commits = git_run(git, 'rev-list', '--max-count=501', head).stdout.splitlines()
    require(0 < len(commits) <= 500, 'History exceeds initial-transfer limit of 500 commits')
    for commit in commits:
        committed_project(git, commit, project_id, check_worktree=False)
        entries = git_run(git, 'ls-tree', '-r', '-z', commit).stdout
        for entry in filter(None, entries.split('\0')):
            info, path = entry.split('\t', 1)
            mode, kind, _ = info.split()
            require(mode in {'100644', '100755'} and kind == 'blob', 'Symlinks/submodules are not transferable')
            require(path == 'project.json' or path.startswith(('artifacts/', 'registries/')),
                    'Unclassified historical file cannot be transferred: ' + path)
        entities = validate_snapshot(git.snapshot(commit))
        for item in entities.values():
            require(item['privacy'] == 'public',
                    'Historical rights are not yet implemented: transfer refused for ' + item['privacy'] +
                    ' entity ' + item['id'] + ' in commit ' + commit)
    return len(commits)


def export_bundle(node, project_id):
    ws = Projects(node).workspace(project_id, blocking=False)
    with ws.journal.lock(), ws.journal.connect() as db:
        ws._branch(); ws._read_locked(db)
        require(not git_run(ws.git, 'status', '--porcelain', '--untracked-files=all').stdout, 'Project must be clean')
        require(git_run(ws.git, 'rev-parse', '--is-shallow-repository').stdout.strip() == 'false', 'Shallow history is not transferable')
        grafts = Path(git_run(ws.git, 'rev-parse', '--git-path', 'info/grafts').stdout.strip())
        require(not (grafts if grafts.is_absolute() else ws.git.root / grafts).exists(), 'Git grafts are not supported')
        head = ws.git.head()
        with tempfile.TemporaryDirectory(prefix='fw-export-') as directory:
            root = Path(directory); repo = root / 'export.git'; repo.mkdir()
            git = Git(repo)
            git_run(git, 'init', '--bare', '--template=', '--initial-branch=main')
            git_run(git, '-c', 'protocol.file.allow=always', 'fetch', '--no-tags', str(ws.git.root), head)
            git_run(git, 'update-ref', 'refs/heads/main', head, '0' * 40)
            # Verify the exact exported graph, independently of source configuration.
            count = validate_history(git, head, project_id)
            path = root / 'project.bundle'
            git_run(git, 'bundle', 'create', str(path), 'refs/heads/main')
            require(path.stat().st_size <= MAX_BUNDLE, 'Bundle exceeds 64 MiB')
            payload = path.read_bytes()
        require(ws.git.head() == head, 'Source changed during export')
        return payload, head, count


def transfer(node, target, project_id, operation_id, ca):
    from spikes.lxc_deployment import SSHSession
    identifier(project_id); identifier(operation_id)
    require(bool(re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*@[A-Za-z0-9][A-Za-z0-9.-]*', target['host'])), 'Invalid SSH host')
    require(bool(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,62}', target['container'])), 'Invalid container')
    service = Administration(node, deployment='desktop')
    view = service.request(ACTOR, {'action': 'list'})
    peer = next((p for p in view['peers'] if p['id'] == target['node_id']), None)
    require(peer and peer['trust'] == 'approved' and peer['fingerprint'] == target['fingerprint'], 'Recipient is not an approved peer')
    check_peer(peer['endpoint'], ca, peer['id'], peer['fingerprint'])
    payload, head, count = export_bundle(node, project_id)
    request = dict(operation_id=operation_id, project_id=project_id, head=head,
                   digest=hashlib.sha256(payload).hexdigest(), source_node_id=view['node_id'],
                   source_pin=view['mapping_identity']['fingerprint'], recipient_node_id=peer['id'], recipient_pin=peer['fingerprint'])
    command = (f"lxc-attach -P /srv/lxc -n {target['container']} -- sh -c " + shlex.quote(
        'cd /opt/federated-workspace/current && runuser -u federated-workspace -- .venv/bin/python -m spikes.git_transfer ' +
        shlex.quote(json.dumps(request))))
    session = SSHSession(target['host'])
    try:
        result = session.run(command, payload)
    finally:
        session.close()
    return f'Transferred {count} public-history commits, HEAD {head}.\n' + result


def import_bundle(request, payload):
    for field in ('operation_id', 'project_id', 'source_node_id', 'recipient_node_id'):
        identifier(request[field])
    require(isinstance(request['head'], str) and bool(re.fullmatch(r'[a-f0-9]{40,64}', request['head'])), 'Invalid source HEAD')
    require(len(payload) <= MAX_BUNDLE and hashlib.sha256(payload).hexdigest() == request['digest'], 'Bundle digest or size differs')
    node = Path('/var/lib/federated-workspace/node.json')
    service = Administration(node)
    view = service.request(ACTOR, {'action': 'list'})
    require(view['node_id'] == request['recipient_node_id'] and view['mapping_identity']['fingerprint'] == request['recipient_pin'], 'Recipient identity changed')
    source = next((p for p in view['peers'] if p['id'] == request['source_node_id']), None)
    require(source and source['trust'] == 'approved' and source['fingerprint'] == request['source_pin'], 'Source is not an approved peer')
    root = node.parent / '.git-transfers'
    require(root == root.resolve(), 'Transfer directory contains symlinks')
    root.mkdir(mode=0o700, exist_ok=True)
    require(root.stat().st_uid == os.getuid() and not root.stat().st_mode & 0o077, 'Unsafe transfer directory')
    fd = os.open(root / 'lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'a+b') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        stage = root / request['operation_id']
        stage.mkdir(mode=0o700, exist_ok=True)
        require(stage == stage.resolve(), 'Unsafe transfer stage')
        record = stage / 'intent.json'
        if record.exists():
            require(record == record.resolve() and json.loads(record.read_text()) == request, 'Operation ID belongs to another request')
        else:
            require(not any(stage.iterdir()), 'Unknown interrupted stage; preserve it for recovery')
            fd = os.open(record, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'w') as output:
                json.dump(request, output); output.flush(); os.fsync(output.fileno())
            sync_dir(stage); sync_dir(root)
        destination_parent = node.parent / 'projects'
        destination_parent.mkdir(mode=0o700, exist_ok=True)
        require(destination_parent == destination_parent.resolve(), 'Destination parent contains symlinks')
        destination = destination_parent / ('project-' + request['project_id'])
        published = stage / 'published'
        if destination.exists():
            require(published.exists(), 'Existing destination is never overwritten')
            git = Git(destination)
            require(git.head() == request['head'] and not git_run(git, 'status', '--porcelain', '--untracked-files=all').stdout, 'Destination changed; recovery refused')
        else:
            require(not os.path.lexists(destination), 'Destination is unsafe')
            bundle = stage / 'project.bundle'
            if bundle.exists():
                require(bundle == bundle.resolve() and hashlib.sha256(bundle.read_bytes()).hexdigest() == request['digest'], 'Staged bundle changed')
            else:
                fd = os.open(bundle, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
                with os.fdopen(fd, 'wb') as output:
                    output.write(payload); output.flush(); os.fsync(output.fileno())
                sync_dir(stage)
            repo = stage / 'repo'
            require(not repo.exists(), 'Interrupted import before publication; preserve stage for manual recovery, no overwrite')
            repo.mkdir(mode=0o700)
            git = Git(repo)
            git_run(git, 'init', '--template=', '--initial-branch=main')
            git_run(git, 'bundle', 'verify', str(bundle))
            git_run(git, '-c', 'protocol.file.allow=always', 'fetch', '--no-tags', str(bundle), 'refs/heads/main:refs/remotes/incoming/main')
            received = git_run(git, 'rev-parse', 'refs/remotes/incoming/main').stdout.strip()
            require(received == request['head'], 'Received HEAD differs')
            validate_history(git, received, request['project_id'])
            git_run(git, 'update-ref', 'refs/heads/main', received, '0' * 40)
            git_run(git, 'read-tree', '--reset', '-u', received)
            # Mark ownership before rename; destination collisions are checked above.
            published.touch(mode=0o600)
            for folder, _, names in os.walk(stage):
                for name in names:
                    with open(Path(folder) / name, 'rb') as entry:
                        os.fsync(entry.fileno())
                sync_dir(folder)
            os.rename(repo, destination); sync_dir(destination_parent); sync_dir(stage)
        creator = ProjectCreation(node)
        from spikes.configuration import parse_node, read_config
        bindings = parse_node(read_config(node), location=node)['projects']
        binding = next((b for b in bindings if b['project_id'] == request['project_id']), None)
        if binding:
            require(binding['root'] == str(destination), 'Project UUID already registered elsewhere')
            if creator.database.exists():
                creator.recover()
        else:
            creator.register(destination, request['operation_id'])
        Projects(node).open(request['project_id'])
        return 'Public project registered on LXC; Git history preserved. No merge or private-data synchronization enabled.'


def main():
    try:
        payload = sys.stdin.buffer.read(MAX_BUNDLE + 1)
        print(import_bundle(json.loads(sys.argv[1]), payload))
        return 0
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
