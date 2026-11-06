# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Bounded owned-file reads through directory descriptors, without symlinks."""
import os
from pathlib import PurePosixPath
import stat
from spikes.metadata import require, safe_path, MAX_FILE


def read_working_file(root,path,limit=MAX_FILE):
    parts=safe_path(path)
    fd=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            next_fd=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
            os.close(fd);fd=next_fd
        content_fd=os.open(parts[-1],os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
        with os.fdopen(content_fd,'rb') as handle:
            before=os.fstat(handle.fileno())
            require(stat.S_ISREG(before.st_mode) and before.st_uid==os.getuid() and before.st_nlink==1,'Expected owned regular working file')
            require(before.st_size<=limit,'Working file exceeds limit')
            raw=handle.read(limit+1);after=os.fstat(handle.fileno());current=os.stat(parts[-1],dir_fd=fd,follow_symlinks=False)
            identity=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
            require(identity(before)==identity(after)==identity(current),'Working file changed while reading; refresh')
    finally:os.close(fd)
    require(len(raw)<=limit,'Working file exceeds limit')
    return raw
