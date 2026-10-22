# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import tempfile
import unittest
from pathlib import Path

from scripts.render_facelift_forms import (SHEETS, covered_form_ids, form_ids,
                                           render_html, validate_inventory, write_pack)
from spikes.desktop_ui import HTML


class FaceliftFormsTests(unittest.TestCase):
    def test_every_current_html_form_is_assigned_to_a_print_sheet(self):
        validate_inventory()
        self.assertEqual(form_ids(HTML), covered_form_ids())
        self.assertEqual(25, len(covered_form_ids()))

    def test_pack_has_unique_sheets_a4_css_and_native_dialogs(self):
        keys = [item['key'] for item in SHEETS]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertGreaterEqual(len(keys), 30)
        rendered = render_html()
        self.assertIn('@page { size: A4 portrait;', rendered)
        self.assertIn('Federace — síťový backend a spojení', rendered)
        self.assertNotIn('Nativní dialog — síťový backend a spojení', rendered)
        self.assertIn('Federace — nasazení LXC uzlu', rendered)
        self.assertNotIn('Nativní dialog — nasazení LXC uzlu', rendered)
        self.assertIn('Nastavení — uživatelský profil', rendered)
        self.assertNotIn('Nativní dialog — uživatelský profil', rendered)
        self.assertIn('Presenter — nastavení gamepadu', rendered)
        self.assertIn('Presenter — displeje a role', rendered)
        self.assertNotIn('Nativní dialog — displeje a role prezentace', rendered)
        self.assertIn('Federace — přenos veřejného projektu do LXC', rendered)
        self.assertNotIn('Nativní dialog — přenos veřejného projektu do LXC', rendered)
        self.assertNotIn('<script src="/app.js"', rendered)

    def test_html_output_is_standalone_and_does_not_require_pdf_renderer(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'forms.html'
            html_path, pdf_path = write_pack(target)
            self.assertEqual(target, html_path)
            self.assertIsNone(pdf_path)
            self.assertIn('article.dataset.sheet', target.read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
