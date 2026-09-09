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
        if self.node_path is None:
            return []
        return parse_node(read_config(self.node_path), location=self.node_path)['projects']

    def list(self):
        # Do not expose filesystem locations or credential references to JavaScript.
        return [{'id': binding['project_id']} for binding in self._bindings()]

    def open(self, project_id):
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
        git = Git(root)
        require(Path(git.run('rev-parse', '--show-toplevel').stdout.strip()) == root,
                'Registration must refer to the repository root')
        # Invalid/uncommitted configuration cannot initialize a journal or index.
        committed_project(git, git.head(), project_id)
        return Workspace(root, state).read_project(project_id)
