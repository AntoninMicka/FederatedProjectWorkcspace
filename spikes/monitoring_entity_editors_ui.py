# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Dedicated entity forms. Complex tasks have no entity editor."""
EDITORS = (
    ('source', 'Zdroj pro těžbu', 'Adresa, podmínky přístupu a nezávislý interval sběru.'),
    ('filter', 'Filtr zpráv', 'Výběrová pravidla, vstupní kanály a cílový pool.'),
    ('pool', 'Pool zpráv', 'Sdílená kolekce, její uchování a původ zpráv.'),
    ('processing', 'Úloha zpracování', 'Vstupy, zadání, rozvrh a konkrétní vykonávající uzel.'),
)
HTML = ''.join(
    '<section id="monitoring-'+kind+'-editor-page" data-monitoring-editor-page hidden>'
    '<header><h3>'+title+'</h3><p>'+description+'</p></header>'
    '<form id="monitoring-'+kind+'-editor" data-monitoring-entity-editor="'+kind+'" hidden>'
    '<div data-monitoring-entity-fields></div><div class="form-actions">'
    '<button type="submit">Uložit '+{'source':'zdroj','filter':'filtr','pool':'pool','processing':'úlohu'}[kind]+'</button>'
    '<button type="button" data-monitoring-entity-cancel>Zrušit</button></div></form></section>'
    for kind, title, description in EDITORS
)
