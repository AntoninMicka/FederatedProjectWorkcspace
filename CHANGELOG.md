<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Changelog

Významné změny veřejných vydání jsou zaznamenané zde. Datum, tag a hashe budou
doplněné až podle skutečně zveřejněného commitu a artefaktů.

## 0.1.0 — připravováno

První veřejný PoC release federovaného projektového workspace.

### Hlavní schopnosti

- Git-backed projekty, bezpečné vytvoření/registrace, Markdown dokumenty,
  metadata, historie, importy a obnovitelné odstranění;
- sdílené responzivní webové/desktopové UI, persistentní konverzace, explicitní
  výběr vstupů, privacy a cílového backendu;
- lokální Ollama, explicitně potvrzované externí AI operace, řízené webové
  hledání a bounded public-source reader;
- creator/opponent workflow, souhrny, extrakce, metadata návrhy, obrazové
  výstupy a verzované Markdown prezentace s presenterem a PDF exportem;
- experimentální federace uzlů, TLS/LXC nástroje a serverový HTTPS režim.

### Distribuční rozsah

- deterministický zdrojový archiv a nebundlovaný Linux `.deb`;
- Python 3.11+, systémový PySide6/Qt WebEngine, Git, Poppler, OpenSSL/OpenSSH,
  PyYAML 6.0.3 a Segno 1.6.6 podle instalační dokumentace;
- ruční instalace a aktualizace; žádný podepsaný balíčkový repozitář ani
  automatický updater.

### Známé hranice

- jde o PoC, nikoli production-ready release;
- plnohodnotná správa federace, obecný Check & Repair, další facelift a
  produkční hardening zůstávají plánované;
- cílová restartová akceptace LXC na Turris Omnia zůstává otevřená;
- volitelné externí služby vyžadují vlastní konfiguraci, credentials a síťovou
  politiku; `local-only` data nesmějí opustit lokální hranici důvěry.
