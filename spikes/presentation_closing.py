# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Locally generated closing slide from a snapshot of the desktop user profile."""
from spikes.user_profile import validate_profile, PROFILE_FIELDS


def closing_slide(profile=None, revision=None):
    profile = validate_profile(profile if profile is not None else {key: '' for key in PROFILE_FIELDS})
    lines = [profile[key] for key in PROFILE_FIELDS if profile[key]]
    qr = ''
    if lines:
        import segno
        qr = segno.make_qr('\n'.join(lines), encoding='utf-8', eci=True, error='m').png_data_uri(scale=6, border=4)
    return dict(id='presentation-closing', deck_revision=revision, closing=True,
                title='Prostor pro Vaše dotazy', bullets=[], body='', notes='',
                background='#102b36', foreground='#ffffff', wallpaper='',
                contacts=lines, qr=qr, repeat=False, reveal='all')
