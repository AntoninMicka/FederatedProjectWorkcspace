"""Local registered-project reads; independent of the HTTP/Qt adapters."""
import os
from pathlib import Path
import stat

from spikes.configuration import parse_node, read_config, committed_project
from spikes.metadata import require
from spikes.storage import Git
from spikes.workspace import Workspace


def directory(value, *, private=False):
    path = Path(value)
    require(path.absolute() == path.resolve(strict=True), 'Symlink directory is unsupported')
    info = path.stat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid(), 'Expected owned directory')
    require(not info.st_mode & 0o022, 'Directory must not be writable by other users')
    if private:
        require(stat.S_IMODE(info.st_mode) == 0o700, 'State directory requires mode 0700')
    return path


class Projects:
    def __init__(self, node_path=None):
        self.node_path = Path(node_path).absolute() if node_path else None

    def _bindings(self):
        if self.node_path is None or not os.path.lexists(self.node_path):
            return []
        return parse_node(read_config(self.node_path), location=self.node_path)['projects']

    def list(self):
        # Do not expose filesystem locations or credential references to JavaScript.
        return [{'id': binding['project_id']} for binding in self._bindings()]

    def workspace(self, project_id, *, blocking=True, deadline=None):
        binding = next((b for b in self._bindings() if b['project_id'] == project_id), None)
        require(binding is not None, 'Project is not registered')
        root = directory(binding['root'])
        state = directory(binding['state_dir'], private=True)
        directory(root / '.git')
        require(state.stat().st_dev == root.stat().st_dev, 'State must be on the project filesystem')
        # Existing SQLite/lock files must not redirect writes out of local state.
        for path in state.iterdir():
            info = path.lstat()
            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                    and info.st_uid == os.getuid() and not info.st_mode & 0o077,
                    'Unsafe state file')
        git = Git(root, deadline=deadline)
        require(Path(git.run('rev-parse', '--show-toplevel').stdout.strip()) == root,
                'Registration must refer to the repository root')
        # Invalid/uncommitted configuration cannot initialize a journal or index.
        committed_project(git, git.head(), project_id)
        return Workspace(root, state, blocking=blocking, deadline=deadline)

    def open(self, project_id):
        return self.workspace(project_id).read_project(project_id)

    def preview(self, project_id, artifact_id, expected_head, page=1):
        import re
        import time
        from spikes.metadata import uuid
        from spikes.artifact_preview import preview
        uuid(project_id); uuid(artifact_id)
        require(isinstance(expected_head, str) and re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', expected_head),
                'Invalid preview commit')
        require(type(page) is int and 1 <= page <= 100, 'Invalid preview page')
        ws = self.workspace(project_id, blocking=False, deadline=time.monotonic() + 30)
        item = ws.read_project(project_id, artifact_id=artifact_id, expected_head=expected_head)
        result = preview(item, page)
        if ws.git.head() != expected_head:
            from spikes.storage import StaleIndex
            raise StaleIndex('Project changed during preview')
        return result
