<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Checklist společného importu NotebookLM

Checklist ověřuje feature `UX-UNIFIED-02C`. Použijte kopii Google Takeout
`.tgz`; importér archiv nemění. Jeden potvrzený notebook vytvoří jeden nový
Workspace projekt.

## Desktop

- [ ] Spusťte desktop a v levém panelu zvolte **Importovat NotebookLM**.
  Formulář se má otevřít jako samostatná stránka mimo přehled projektů;
  samostatné Qt okno ani toolbar tlačítko se nemá zobrazit.
- [ ] Zvolte **Vybrat Takeout TGZ…**. Stránka smí zobrazit jen název vybraného
  souboru; nesmí dostat jeho lokální cestu. Poté načtěte bezpečný přehled.
- [ ] Vyberte právě jeden notebook, privacy a zvolte **Vybrat prázdnou cílovou
  složku…**. Systémový picker se musí otevřít i po předchozím pickeru archivu;
  po výběru se zobrazí přesná cesta potvrzená systémovým pickerem. Zrušení
  pickeru nesmí změnit plán. Neplatná složka musí vypsat chybu ve stránce.
  Pokud je vybraná prázdná složka ve vlastnictví aktuálního uživatele, ale má
  například práva `0775`, dialog musí ukázat aktuální práva a nabídnout změnu
  na `0700`; odmítnutí nesmí práva změnit ani složku přijmout. Po souhlasu
  připravte nový plán. Desktop má nabízet i **Jen na tomto počítači**.
- [ ] Zkontrolujte zvýrazněný řádek **Cíl projektu**. Po ručním výběru má cestu
  ukázat hned; při výchozím umístění se přesná cesta doplní přípravou plánu.
- [ ] Připravte plán a zkontrolujte název, přesný cíl, privacy, počet položek,
  varování, shodné existující importy a digest.
- [ ] Bez zaškrtnutí potvrzení nesmí jít import spustit. Po potvrzení se má
  vytvořit a otevřít jediný projekt s jediným počátečním commitem.
- [ ] Po úspěchu ověřte, že vybraná cílová složka má práva `0700`, obsahuje
  `.git` a `project.json` a že nový projekt zůstane v katalogu i po restartu.

## Web/LXC

- [ ] Přihlaste se jako `node-admin` nebo `federation-admin`. Běžný člen
  nesmí tlačítko importu ani API použít. Správci se samostatná stránka otevře
  stejným tlačítkem v levém panelu.
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
