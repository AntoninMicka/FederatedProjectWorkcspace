<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Library replacement and debugging

## Current Linux design

The application is delivered as editable Python source. The `.deb` launcher starts
`/usr/bin/python3 -I` and imports system PySide6/Qt libraries. No frozen interpreter,
private Qt runtime or library integrity lock is added by this compliance patch.
The source archive includes the application and packaging scripts needed to rebuild it.

Python's `-I` ignores `PYTHONPATH` and user-site packages. Therefore, merely setting
`PYTHONPATH` is **not** a documented replacement procedure for the installed launcher.
It is also not necessary to weaken the launcher's isolation to exercise library rights.

## System-package procedure

Use a disposable test machine or container with the supported desktop environment.
Record the original binary/source package versions for Python, PySide6, Shiboken,
Qt modules, WebEngine and plugins. Obtain the corresponding source packages from
the distribution or the appropriate upstream release, apply the intended library
change, and rebuild compatible system packages using their supplied build recipes.
Install them in the test system and run the **unchanged workspace package**.

Verify that the changed library is actually loaded (module/library paths and a
non-sensitive diagnostic for the change), then run the desktop and relevant
functional/smoke tests. Retain package hashes, source identification, build instructions
and the results. A normal run with the unmodified distribution library is not proof
that a modified library can be substituted.

This is the intended LGPL section 4(d)(1) shared-library route. Its suitability,
including compatibility of a modified interface-compatible library, must be validated
for the release platform. That validation has **not** been completed by this baseline.

## Source and development route

A recipient can modify the workspace sources and build scripts, including the launcher,
and rebuild the package under the applicable licenses. A separate environment with
compatible modified PySide6/Qt packages may also be used to run the source directly.
Do not silently introduce PyQt, a commercial-only Qt module or a bundled wheel while
claiming to preserve the same reviewed distribution scope.

## Rights and limits

No additional workspace term prohibits modification of the LGPL portions or reverse
engineering to debug those modifications. No new warranty, support promise or
commercial Qt license is granted by this document. Third-party license conditions
continue to apply. A device deployment that prevents installation of modified software
requires a separate review, including any applicable installation-information duties.

See [LGPL v3 section 4](licenses/COPYING.LGPL-3.0) and
[third-party notices](../../THIRD_PARTY_NOTICES.md).
