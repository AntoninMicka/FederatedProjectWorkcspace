# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Workspace UI facade for explicit cross-project sharing (XREF-02, ADR 0086).

Only CrossReferences resolves sources and writes; this module composes its
authorized views into preview/confirm envelopes. Projects the actor cannot see
are skipped without revealing their IDs, titles or existence.
"""
from uuid import uuid4

from spikes.administration import AccessDenied
from spikes.cross_references import CrossReferences, ReferenceUnavailable
from spikes.metadata import require, uuid
from spikes.reference_schema import PURPOSES, active, reason as valid_reason, single_line
from spikes.reporting_schema import digest, encoded


def envelope(value, display):
    return dict(preview=value, sha256=digest(encoded(value)), display=display)


class ArtifactSharing:
    def __init__(self, references):
        require(isinstance(references, CrossReferences), 'Sharing requires the reference service')
        self.references = references

    def _visible(self, exclude=()):
        rows = []
        for project_id in self.references.registered_projects():
            if project_id in exclude:
                continue
            try:
                rows.append(self.references.project_state(project_id))
            except (AccessDenied, ValueError, OSError):
                continue  # Hidden or unavailable: no ID, title or reason leaks.
        return rows

    @staticmethod
    def _share_row(share_id, record, state, visible_titles):
        artifact = state['artifacts'].get(record['artifact_id'])
        return dict(share_id=share_id, artifact_id=record['artifact_id'],
                    artifact_title=artifact['title'] if artifact else None,
                    available=artifact is not None, purpose=record['purpose'], reason=record['reason'],
                    originator_id=record['originator_id'], created_at=record['created_at'],
                    revoked=record['revoked'],
                    targets=[dict(id=t, title=visible_titles[t]) for t in record['targets'] if t in visible_titles])

    def overview(self, project_id):
        """Offers into, shares from and references in one project, for one actor."""
        uuid(project_id)
        own = self.references.project_state(project_id)
        others = self._visible(exclude={project_id})
        titles = {row['project_id']: row['title'] for row in others}
        attached = {}
        for ref_id, value in own['references'].items():
            if value.get('share'):
                attached.setdefault(value['share']['share_id'], []).append(ref_id)
        offers = []
        for state in others:
            for share_id, record in state['shares'].items():
                if active(record, project_id) and record['artifact_id'] in state['artifacts']:
                    row = self._share_row(share_id, record, state, {})
                    del row['targets']
                    offers.append(dict(row, source_project_id=state['project_id'],
                                       source_title=state['title'],
                                       privacy=state['artifacts'][record['artifact_id']]['privacy'],
                                       attached_reference_ids=sorted(attached.get(share_id, []))))
        shares = []
        for share_id, record in own['shares'].items():
            row = self._share_row(share_id, record, own, titles)
            row['usage'] = [dict(project_id=state['project_id'], project_title=state['title'], reference_id=ref_id,
                                 title=state['artifacts'].get(ref_id, {}).get('title'))
                            for state in others for ref_id, value in state['references'].items()
                            if value['source']['project_id'] == project_id
                            and (value.get('share') or {}).get('share_id') == share_id]
            shares.append(row)
        refs = []
        for ref_id, value in own['references'].items():
            source = value['source']
            refs.append(dict(reference_id=ref_id, title=own['artifacts'].get(ref_id, {}).get('title'),
                             schema=value['schema'], share=value.get('share'),
                             source_project_id=source['project_id'],
                             source_title=titles.get(source['project_id']),
                             source_artifact_id=source['artifact_id'], commit_id=source['commit_id'],
                             privacy=own['artifacts'].get(ref_id, {}).get('privacy')))
        key = lambda row: (row.get('artifact_title') or row.get('title') or '', row.get('share_id') or row.get('reference_id'))
        return dict(project_id=project_id, commit_id=own['commit_id'],
                    candidates=sorted((dict(id=r['project_id'], title=r['title']) for r in others),
                                      key=lambda r: (r['title'], r['id'])),
                    offers=sorted(offers, key=key), shares=sorted(shares, key=key), references=sorted(refs, key=key))

    def share_preview(self, project_id, artifact_id, targets, purpose, reason):
        require(purpose in PURPOSES, 'Invalid share purpose'); valid_reason(reason); reason_text = reason
        value = self.references.share_preview(project_id, str(uuid4()), artifact_id, list(targets), reason_text,
                                              purpose=purpose)
        state = self.references.project_state(project_id, extra_ids=(artifact_id,))
        titles = {row['project_id']: row['title'] for row in self._visible(exclude={project_id})}
        meta = state['artifacts'][artifact_id]
        return envelope(value, dict(source_title=state['title'], artifact_title=meta['title'],
                                    privacy=meta['privacy'], purpose=purpose, reason=reason_text,
                                    targets=[dict(id=t, title=titles.get(t)) for t in value['record']['targets']]))

    def share_confirm(self, preview, sha256, operation_id):
        return self.references.share_write(preview, operation_id, sha256, confirm=True)

    def attach_preview(self, project_id, source_project_id, share_id, title, reason):
        uuid(project_id); uuid(source_project_id); uuid(share_id); single_line(title); valid_reason(reason)
        reason_text = reason
        require(source_project_id != project_id, 'Cross-project reference requires another project')
        state = self.references.project_state(source_project_id)
        record = state['shares'].get(share_id)
        if record is None or not active(record, project_id):
            raise ReferenceUnavailable('share-revoked' if record and record['revoked'] else 'not-shared')
        pin = self.references.source_pin(source_project_id, record['artifact_id'])
        value = self.references.preview(project_id, str(uuid4()), pin, title, share_id=share_id, reason_text=reason_text)
        meta = state['artifacts'].get(record['artifact_id'], {})
        return envelope(value, dict(source_title=state['title'], artifact_title=meta.get('title'),
                                    purpose=record['purpose'], share_reason=record['reason'],
                                    commit_id=pin['commit_id'], path=pin['path'], sha256=pin['sha256'],
                                    privacy=value['privacy'], title=title, reason=reason_text))

    def attach_confirm(self, preview, sha256, operation_id):
        return self.references.write(preview, operation_id, sha256, confirm=True)

    def reference_view(self, project_id, reference_id):
        """Read-only pinned view; an unavailable source is a visible state, not an error page."""
        try:
            view = self.references.view(project_id, reference_id)
        except ReferenceUnavailable as exc:
            head, value, meta = self.references.local(project_id, reference_id)
            return dict(project_id=project_id, reference_id=reference_id, commit_id=head, read_only=True,
                        schema=value['schema'], share=value.get('share'), state=exc.state, stale=False,
                        privacy_unverified=False, source=value['source'], newer=None, privacy=meta['privacy'],
                        title=meta['title'], preview=None, source_title=None)
        view.pop('content_b64', None)  # The inert preview carries what the UI renders.
        try:
            view['source_title'] = self.references.project_state(view['source']['project_id'])['title']
        except (AccessDenied, ValueError, OSError):
            view['source_title'] = None
        return view
