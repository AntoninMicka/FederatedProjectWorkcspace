# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
#
"""Required public licensing files for the current Linux desktop distributions."""
from pathlib import Path

LICENSE_FILES = (
    'LICENSE',
    'THIRD_PARTY_NOTICES.md',
    'docs/legal/COMPLIANCE.md',
    'docs/legal/DEPENDENCIES.toml',
    'docs/legal/LICENSE_SOURCES.md',
    'docs/legal/RELINKING.md',
    'docs/legal/licenses/COPYING.GPL-3.0',
    'docs/legal/licenses/COPYING.LGPL-3.0',
    'docs/legal/licenses/LICENSE.PyYAML-6.0.3',
)


def license_files(root: Path) -> list[Path]:
    """Fail closed if a required notice is missing, empty or linked outside the tree.

    Run packaging from a trusted, quiescent checkout: these checks do not provide
    a sandbox against concurrent filesystem changes. Never recursively include
    arbitrary compliance evidence; it can contain private build-machine details.
    """
    root = Path(root).absolute()
    files = [root / name for name in LICENSE_FILES]
    for path in files:
        if (not path.is_file() or path.is_symlink()
                or path.resolve() != path.absolute() or path.stat().st_size == 0):
            raise ValueError(f'Expected non-empty regular licensing file: {path.relative_to(root)}')
    return files
