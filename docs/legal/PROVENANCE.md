<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Source provenance

## Project-originated material

Unless explicitly identified otherwise, source code and documentation in this
repository are original project material created under the direction of
Antonín Mička and distributed under MPL-2.0.

Development may use AI-assisted drafting and coding tools. AI assistance does
not imply incorporation of third-party source code.

## Imported or reused material

Any material copied or adapted from another repository, publication, example,
snippet, or third-party source must record:

- source / URL or repository,
- original author or copyright holder where known,
- original license,
- date imported,
- files affected,
- modifications made,
- compatibility decision.

Third-party material must not be marked as solely copyrighted by Antonín Mička.

## Current distributed-set review

The pre-release provenance review for commit
`128928e9fe88f9e353a22ca8bdd0db3922126301` covered the 100 files selected by the
current source-archive builder, excluding the generated manifest. All are UTF-8 text;
no binary asset, vendored dependency tree, font, model, media file or third-party
executable is included by that builder.

Project source and documentation in that set carry the project SPDX declaration.
The only third-party text intentionally shipped in the reviewed set is the preserved
license/notice material listed in `THIRD_PARTY_NOTICES.md` and
`docs/legal/licenses/`; those files retain their upstream ownership and terms.
`spikes/libgit2/probe.cpp` is project test-driver source and does not contain a copy of
libgit2; libgit2 itself is only an optional external build/test dependency.

Early roadmap, architecture and IP-planning documents are classified as
project-originated, including AI-assisted drafting under project direction. No
third-party copyright header, vendored source or copied asset was identified in their
distributed bytes. This is a provenance review, not a plagiarism or global code
similarity scan. If a future contribution copies or adapts external material, the
recording rules above apply and this gate must be reopened for the affected files.

**Closure status for the current distributed set: PASS.**

## Release 0.1.0 candidate delta review

On 2026-10-21 the allowlist produced from release base `9fb4262` plus the
release-preparation worktree selected 257 regular files, excluding the generated
manifest. All selected files decoded as UTF-8; no binary asset, vendored dependency,
font, model, media file or executable was selected. The two JSON module declarations
cannot carry comment-form SPDX headers and `VERSION` is generated release metadata;
the remaining project files carry an SPDX license declaration, while preserved
third-party license texts retain their upstream terms.

The delta since the historical 100-file audit consists of project implementation,
tests, schemas/declarations and documentation already tracked by this repository,
plus the release metadata in this batch. No copied Segno code is included: the
source archive and `.deb` only declare/use an external installation. This review is
bound to the named base and current release diff; its final commit ID and artifact
hashes remain pending under CE-01 until a clean commit is built.

**Candidate delta status: PASS for preparing the unbundled 0.1.0 artifacts; not a
published-release approval.**

## AI-assisted development

AI tools are used as development assistants. Contributors remain responsible
for reviewing generated output and must not knowingly submit copied
third-party material incompatible with the project license.

`REUSE_CATALOG.private.md` is an internal working document excluded by the current
source and `.deb` builders. It is outside the reviewed distributed set and must be
reviewed separately before any future distribution.
