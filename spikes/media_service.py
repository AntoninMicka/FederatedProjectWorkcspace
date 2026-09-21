# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Node-local image backend configuration shared by desktop and web UI."""
import os
from pathlib import Path
import stat

from spikes.media_backend import ComfyBindings, MEDIA_BACKENDS
from spikes.metadata import require


class MediaService:
    def __init__(self, node_path, *, state_dir=None):
        self.node_path = Path(node_path).absolute()
        self.state_dir = (Path(state_dir).absolute() if state_dir else
                          self.node_path.parent / ('.' + self.node_path.name + '.chat'))

    def _root(self):
        if not os.path.lexists(self.state_dir): self.state_dir.mkdir(mode=0o700)
        info = self.state_dir.lstat()
        require(self.state_dir.absolute() == self.state_dir.resolve()
                and stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
                and stat.S_IMODE(info.st_mode) == 0o700,
                'Media state directory requires owned mode 0700 without symlinks')
        return self.state_dir

    def configure_comfy(self, value):
        binding = MEDIA_BACKENDS.parse_binding(value)
        require(binding.adapter_id == 'comfyui', 'ComfyUI binding is required')
        ComfyBindings(self._root()).save(binding)
        return {'binding': binding.serialize()}

    def status(self):
        try: binding = ComfyBindings(self._root()).load().serialize()
        except FileNotFoundError: binding = None
        return {'comfyui': binding}
