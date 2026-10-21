<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Sources and hashes of licensing evidence

Evidence date: **2026-09-10**. Baseline project commit:
`84c06ce9b29ba4bdf4cdaa7557c09186f7a6ede5`.

## Delivered license texts

| File under `docs/legal/licenses/` | Bytes | SHA-256 |
| --- | ---: | --- |
| `COPYING.GPL-3.0` | 35149 | `3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986` |
| `COPYING.LGPL-3.0` | 7652 | `e3a994d82e644b03a792a930f574002658412f62407f5fee083f2555c5f23118` |
| `LICENSE.PyYAML-6.0.3` | 1101 | `8d3928f9dc4490fd635707cb88eb26bd764102a7282954307d3e5167a577e8a4` |

`LICENSE.PyYAML-6.0.3` is the complete, unaltered `LICENSE` returned from the
upstream `yaml/pyyaml` tag `6.0.3`. Its Git blob SHA is
`2f1b8e15e5627d92f0521605c9870bc8e5505cb4`; the reconstructed bytes were checked
against that SHA. Source: https://github.com/yaml/pyyaml/blob/6.0.3/LICENSE.

`COPYING.GPL-3.0` and `COPYING.LGPL-3.0` are complete, unmodified copies of
`/usr/share/common-licenses/GPL-3` and `/usr/share/common-licenses/LGPL-3` in the
preparation environment. These are GNU license-document copies, not the copyright
files of the user's Qt packages. They preserve the FSF copyright and permission
to distribute verbatim license copies. Canonical references:
https://www.gnu.org/licenses/gpl-3.0.html and
https://www.gnu.org/licenses/lgpl-3.0.html.
The GNU plain-text endpoints timed out during preparation; no successful fresh
byte-for-byte download comparison with those endpoints is claimed. The LGPL
section 4 conditions were checked against the accessible official GNU page at
https://www.gnu.org/licenses/lgpl.html.

The project's root `LICENSE` is retained without modification. These ancillary
texts do not apply an alternative license to workspace code and are not declarations
that all third-party notice obligations are closed.

## Repository inputs checked

| Input at the baseline commit | Git blob SHA | Evidence scope |
| --- | --- | --- |
| `scripts/package_deb.py` | `441708005563a76e7d90b362a24148e4ef110199` | Full file, reconstructed bytes hash-checked |
| `scripts/package_desktop.py` | `6dce80b365105e2edb3ed6f7228771fe2fd103fa` | Full file, reconstructed bytes hash-checked |
| `tests/test_package_deb.py` | `fc1cd1e24d0d8d7ab9a225ccb81b0ca75318c1e2` | Existing packaging tests read |
| `tests/test_package_desktop.py` | `d5865466a24b40f1bed0f75db3e6467b79440c13` | Existing packaging tests read |
| `spikes/artifact_preview.py` | `f47389ed8286acae12f2761509fb9ee3a7176b23` | Full file, external pdftoppm call checked |
| `spikes/desktop.py` | `8aa0c165a31083b008242b6bafa8c06596922ece` | First 75 lines read for runtime integration; not a full-file audit |

## Primary license references reviewed

- MPL file licensing and notices: https://www.mozilla.org/en-US/MPL/2.0/FAQ/
- LGPL obligations: https://www.gnu.org/licenses/lgpl.html
- PySide6 representative library header, `v6.10.2`, lines 1–12:
  https://github.com/pyside/pyside-setup/blob/v6.10.2/sources/pyside6/libpyside/pyside.cpp
  (whole-file blob SHA `1f55b30d790c0aeb4a40315e8a00e1b56b3807d4`).
- Shiboken representative runtime header, `v6.10.2`, lines 1–8:
  https://github.com/pyside/pyside-setup/blob/v6.10.2/sources/shiboken6/libshiboken/basewrapper.cpp
  (whole-file blob SHA `eb9d47c7f17a06f63005eb0f1f38ef31db0049de`).
- Qt module policy: https://doc.qt.io/qt-6/licensing.html
- WebEngine / Chromium: https://doc.qt.io/qt-6/qtwebengine-licensing.html
- Qt for Python third-party notices: https://doc.qt.io/qtforpython-6/licenses.html
- Python license history: https://docs.python.org/3/license.html
- SQLite core copyright: https://www.sqlite.org/copyright.html
- libgit2 `v1.9.1` COPYING, first 60 lines including linking exception:
  https://github.com/libgit2/libgit2/blob/v1.9.1/COPYING
  (whole-file blob SHA `701792e9acb0875bf4266a97d63a0d5e8b7f0257`).
- REUSE license-file and annotation rules: https://reuse.software/spec/

General documentation may describe a newer release than the user's installed
package. The tagged headers above support the reference-library licensing route;
they are not proof of the exact downstream runtime. Individual file blob IDs are
not repository commit IDs. Preserve those distinctions when updating this evidence.
