<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Checklist společného importu NotebookLM

Checklist ověřuje feature `UX-UNIFIED-02C`. Použijte kopii Google Takeout
`.tgz`; importér archiv nemění. Jeden potvrzený notebook vytvoří jeden nový
Workspace projekt.

## Desktop

- [ ] Spusťte desktop a na stránce **Projekty** rozbalte **Importovat celý
  projekt z NotebookLM**. Samostatné Qt okno ani toolbar tlačítko se nemá
  zobrazit.
- [ ] Zvolte **Vybrat Takeout TGZ…**. Stránka smí zobrazit jen název vybraného
  souboru; nesmí dostat jeho lokální cestu. Poté načtěte bezpečný přehled.
- [ ] Vyberte právě jeden notebook, privacy a volitelně existující prázdnou
  cílovou složku. Desktop má nabízet i **Jen na tomto počítači**.
- [ ] Připravte plán a zkontrolujte název, přesný cíl, privacy, počet položek,
  varování, shodné existující importy a digest.
- [ ] Bez zaškrtnutí potvrzení nesmí jít import spustit. Po potvrzení se má
  vytvořit a otevřít jediný projekt s jediným počátečním commitem.

## Web/LXC

- [ ] Přihlaste se jako `node-admin` nebo `federation-admin`. Běžný člen
  nesmí importní sekci ani API použít.
- [ ] Zadejte absolutní server-local cestu k TGZ a projděte stejný
  přehled → plán → potvrzení. Web nesmí nabízet desktopový picker ani
  privacy `local-only`.
- [ ] Po importu otevřete katalog a několik zdrojů/výstupů. HTML/JSON se má
  zobrazit pouze jako bezpečně odvozený Markdown/text, nikdy jako aktivní HTML.

## Restart a chybové hranice

- [ ] Změňte po přípravě plánu archiv, notebook, privacy nebo cíl. Staré
  potvrzení se musí zneplatnit a je nutné připravit nový plán.
- [ ] Zopakujte potvrzení stejné operace. Musí se vrátit stejný receipt,
  projekt UUID a commit, nikoli druhý projekt.
- [ ] Restartujte aplikaci po dokončení. Projekt musí zůstat v katalogu a
  importované bajty i náhledy musí být dostupné.
- [ ] Pokud aplikace spadne během potvrzeného vytvoření, spusťte ji znovu.
  `ProjectCreation` recovery musí dokončit nebo fail-closed nahlásit jednu
  operaci; ručně nekopírujte staging a nespouštějte import s novým ID naslepo.
