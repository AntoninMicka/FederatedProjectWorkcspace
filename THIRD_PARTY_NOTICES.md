<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Third-party notices

This workspace uses third-party software. The project's own covered source files
remain under Mozilla Public License 2.0; see [LICENSE](LICENSE). The licenses,
copyrights and trademarks of third parties remain with their respective holders.
Including a license text here does **not** relicense the workspace under that license.

## Distribution covered by this notice

This baseline covers the Linux source archive and the `.deb` built by
`scripts/package_desktop.py` and `scripts/package_deb.py`. Those builders package
workspace sources and documentation, **not copies of the Python, PyYAML, Qt,
PySide6, Shiboken, Git or Poppler runtimes**. A source installation may obtain
PyYAML separately using pip; the `.deb` uses operating-system packages.

These notices are not a complete runtime SBOM or a legal clearance of a release.
Exact package versions, downstream patches, transitive dependencies and enabled
features depend on the target operating system. See
[compliance evidence and release checks](docs/legal/COMPLIANCE.md) and the
[dependency register](docs/legal/DEPENDENCIES.toml).

## Qt for Python: PySide6 and Shiboken runtime

The desktop uses PySide6 and the Shiboken runtime, together with Qt libraries
including Qt Core, Widgets and WebEngine. The intended open-source licensing
route for the LGPL-covered library portions is **LGPL version 3**. The Qt Company
Ltd. and other contributors hold the relevant copyrights. The library copyright
statements and any component-specific third-party notices supplied with the
installed packages remain applicable.

Representative PySide6 and Shiboken runtime source headers at `v6.10.2` provide
an LGPL-3.0-only option, alongside other licensing alternatives. This is evidence
for the selected route, not a blanket statement that every tool, example or module
in Qt for Python is LGPL. No commercial Qt entitlement is claimed. Adding a module,
copying an example, or bundling a wheel requires a separate review.

The libraries and their use under this route are covered by the LGPL.
Copies of the [GNU LGPL v3](docs/legal/licenses/COPYING.LGPL-3.0) and
[GNU GPL v3](docs/legal/licenses/COPYING.GPL-3.0) accompany this distribution.

The workspace imposes no additional restriction on modification of the LGPL
library portions or reverse engineering for debugging those modifications.
The distribution is designed to load system-supplied libraries rather than a
private frozen runtime. Instructions and the remaining validation requirement
are in [Library replacement and debugging](docs/legal/RELINKING.md).

Upstream evidence:
- https://github.com/pyside/pyside-setup/blob/v6.10.2/sources/pyside6/libpyside/pyside.cpp
- https://github.com/pyside/pyside-setup/blob/v6.10.2/sources/shiboken6/libshiboken/basewrapper.cpp
- https://doc.qt.io/qtforpython-6/licenses.html

## Qt WebEngine and Chromium

Qt WebEngine incorporates Chromium and third-party components with multiple
licenses. The LGPL route for the Qt-specific library parts does not replace
Chromium or other third-party notices. The workspace's current Linux builders
do not bundle Qt WebEngine binaries, Chromium resources or their source trees.
The installed operating-system packages provide the corresponding copyright
files; the release evidence must record the actual providers and versions.

A future AppImage, container image, standalone executable, copied virtual
environment or wheel bundle is a different distribution scope. Before releasing
one, collect and ship notices and any corresponding sources required for the
actual Qt/Chromium build, plugins, codecs, fonts and other included components.
A link to this page alone is not a substitute for required delivered notices.

Upstream: https://doc.qt.io/qt-6/qtwebengine-licensing.html

## PyYAML 6.0.3

PyYAML is used for YAML parsing and is licensed under the MIT License.
The upstream copyright and permission notice is reproduced **without alteration**
in [LICENSE.PyYAML-6.0.3](docs/legal/licenses/LICENSE.PyYAML-6.0.3):

Copyright (c) 2017-2021 Ingy döt Net
Copyright (c) 2006-2016 Kirill Simonov

Source: https://github.com/yaml/pyyaml/blob/6.0.3/LICENSE

PyYAML's optional C extension can use LibYAML. Whether LibYAML is dynamically
provided or embedded in a wheel must be checked against the exact installation
artifact. The PyYAML MIT notice is not asserted to cover all contents of every
possible wheel. No PyYAML wheel or LibYAML binary is shipped by the current builders.

## Other system components and external programs

Python and its standard library have the PSF license history and component-specific
notices documented at https://docs.python.org/3/license.html. SQLite core is
published in the public domain: https://www.sqlite.org/copyright.html.
This does not classify every extension or downstream package as public domain.

The workspace invokes Git as a separate program. PDF previews invoke `pdftoppm`
from Poppler using a subprocess and data streams. Shell launchers also use system
utilities such as `readlink` and `dirname`. These programs are not copied into the
workspace package. Record their **actual installed providers**, versions and
license notices; a package called `coreutils` need not identify a single
implementation on all supported distributions.

Using an external executable is recorded separately from in-process library
linking. This is a description of the current integration, not a general exemption
from the GPL or permission to copy an executable without its notices and sources.

## Optional libgit2 experiment

The source archive includes the workspace's `spikes/libgit2/probe.cpp`, not libgit2
itself. The `.deb` does not ship the probe or libgit2. Upstream libgit2 `v1.9.1`
uses GPL version 2 with its own linking exception; see
https://github.com/libgit2/libgit2/blob/v1.9.1/COPYING.
That exception is not permission to omit obligations for distributing the library
itself or a modified version. Distributing a compiled probe needs a new artifact check.

## Where installed package notices can be found

On Debian-family systems, inspect `/usr/share/doc/<binary-package>/copyright`
and any referenced license files for the actual installed packages. Package names
may be split by Qt module, architecture or provider. The workspace's copies of
these notices and the included LGPL/GPL texts are installed beneath
`/usr/share/doc/federated-workspace-poc/`, preserving the relative paths above.
No endorsement by any third-party project is implied.
