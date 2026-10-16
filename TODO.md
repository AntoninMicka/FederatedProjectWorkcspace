<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — F-M4-PRESENTER-PDF-01

Aktivní dávka **F-M4-PRESENTER-PDF-01 — export prezentace a záznamy
uskutečněných relací** navazuje na doručené `F-M4-PRESENTER-01` (PR #68,
merge commit `aa7fa26`). Cílová úroveň je **PoC validated**.

- Větev: `feature/f-m4-presenter-pdf-01`
- Základ/cíl PR: aktuální `develop` (`aa7fa26`) → `develop`
- Původ: `F-M4-PRESENTER-PDF-01` z BACKLOG a rozšíření uživatelem 2026-10-16:
  každá uskutečněná relace má mít vlastní záznam, seznam v editoru a akce
  smazat a vytisknout.
- Rozsah: přesný veřejný průběh relace, jeho durable záznam a správa v editoru;
  tisk/PDF uloženého decku nebo uložené relace. Soukromé poznámky, preview,
  nepromítnuté backupy a volné HTML do záznamu ani exportu nepatří.
- Mimo rozsah: redesign editoru/presenteru, obecný reporting a zveřejňování
  relací jako DisclosureEvent.

## Crash a recovery hranice

Živá relace se před potvrzením prvního veřejného výstupu založí v lokálním
SQLite journalu mimo projektový Git. Každý potvrzený audience snapshot se do
něj zapíše dříve, než API oznámí úspěch; výběr v soukromém preview se
nezapisuje. Ukončení relace materializuje jediný verzovaný projektový dokument
přes existující `Workspace.transact`/journal/Git/index hranici se stabilním ID
artefaktu i operace. Pád před commitem obnoví existující journal, pád po
commitu dovolí obnovit index z HEAD; lokální relace se označí materializovaná
až po úspěšném návratu transakce. Po restartu se rozpracovaná relace uzavře jako
přerušená a znovu materializuje idempotentně, nikoli rekonstrukcí z aktuálního
decku.

PDF vznikne až po explicitním výběru cíle a potvrzení zobrazeného plánu. Tiskne
se do dočasného souboru ve stejné složce a teprve hotový výsledek se atomicky
přejmenuje na cíl. Zrušení a známé selhání nesmí ponechat cílový soubor v
částečném stavu; po pádu může zůstat pouze jednoznačně pojmenovaný dočasný
soubor k bezpečnému úklidu/opakování.

## Úkoly dávky

- [x] [completed] **F-M4-PRESENTER-PDF-01-A — kontrakt relace a reuse
  (designed).** Definovat omezené schema veřejných snapshotů, identitu zdroje,
  stav ukončení, vazbu na revizi a výše uvedené recovery hranice. Reuse:
  adaptovat `PresentationDocuments`, `Artifacts.save`, existující transakční
  hranici a bezpečný renderer; odmítnout druhý volný HTML renderer.
- [x] [completed] **F-M4-PRESENTER-PDF-01-B — durable zachycení a materializace
  relace (implemented).** Založit relaci při skutečném spuštění, atomicky
  přidávat jen potvrzené veřejné snapshoty a uzavírat ji jako dokončenou nebo
  po restartu přerušenou do projektového artefaktu.
- [x] [completed] **F-M4-PRESENTER-PDF-01-C — seznam a mazání v editoru
  (implemented).** U decku zobrazit jeho relace se stavem, časem a počtem
  stránek. Smazání musí mít preview, explicitní potvrzení, exact-HEAD kontrolu
  a zachovat Git historii.
- [x] [completed] **F-M4-PRESENTER-PDF-01-D — bezpečný tisk/PDF
  (implemented).** Kanonický režim tiskne hlavní `next` linii; relace tiskne
  uložené audience snapshoty v přesném pořadí včetně backupů, opakování,
  závěru a reveal stavů. Oba používají stejný allowlisted vizuální model,
  16:9, offline zdroje a dvoufázový výběr cíle/potvrzení.
- [ ] [in progress] **F-M4-PRESENTER-PDF-01-E — UI, testy, dokumentace a fyzická
  akceptace (PoC validated).** Ověřit prázdnou/přerušenou relaci, restart,
  stale HEAD, idempotentní recovery, zrušení cíle, přepis, pád při zápisu,
  stabilní pořadí a vyloučení soukromých polí. Spustit celou testovací sadu a
  na desktopu vizuálně porovnat výsledné PDF s audience výstupem.

## Průběžné ověření 2026-10-16

- Cílené modelové, storage, UI-policy a atomické publikační testy jsou úspěšné;
  pokrývají completed/interrupted relaci, exact public reveal snapshoty,
  nejisté potvrzení po commitu bez duplicity, potvrzené smazání se zachovanou
  historií, kanonický/relační náhled a zachování původního PDF při známém
  selhání.
- Celá sada po opravě fyzicky nalezených regresí: `619 tests`, `OK`, `27 skipped`.
  Přeskočené testy
  vyžadují skutečný WebEngine, soukromý vzorek, nativní Git probe nebo živé
  služby a nejsou vydávány za fyzickou akceptaci této feature.
- Samostatný headless Qt WebEngine smoke skutečně vytvořil dvoustránkový PDF;
  `pdfinfo` potvrdil `2` strany, rozměr `1152 × 648 pt` (16:9) a PDF 1.4.
- Fyzická kontrola odhalila dvě blokující regrese: evidence relace odmítala
  allowlistované ID lokálně generovaného závěrečného slajdu a validátor nativní
  akce nepředal ověřené nonce obsluze PDF dialogu. Opakovaná kontrola exportu
  odkryla ještě vlastní příčinu tichého selhání: použitý PySide6 nepřevedl JS
  objekt na Python `dict`. PDF most nyní přenáší explicitní bounded JSON,
  validuje nonce i digest a chybu ukáže v dialogu. Kontrakty kryjí regresní testy
  a skutečný offscreen WebEngine probe. Po úplném restartu desktopu uživatel
  fyzicky ověřil výběr cílového souboru, zpřístupnění potvrzení i dokončení PDF
  exportu jako funkční; ostatní níže uvedené scénáře ještě zbývají.
- Zbývá fyzicky v desktopu ověřit: dokončenou i po restartu přerušenou relaci v
  seznamu, tisk kanonického decku a relace, zrušení výběru cíle, přepsání
  existujícího PDF, vizuální shodu s audience rendererem a potvrzené smazání.

## Akceptační podmínky

- Každé skutečné spuštění presenteru založí samostatný durable záznam a po
  pádu aplikace se již potvrzený veřejný průběh neztratí ani nedoplní z jiné
  revize decku.
- Editor zobrazí relace vybraného decku a umožní jejich potvrzené smazání a
  tisk; odstranění zachová dohledatelnost v Git historii.
- Kanonický a odprezentovaný export jsou viditelně odlišené a neobsahují notes,
  soukromý preview ani nepromítnutý obsah.
- PDF se publikuje až po potvrzení úplného plánu a cíle; zrušení ani selhání
  nepoškodí existující cílový soubor.
- Cílené testy, celá sada, `git diff --check` a fyzická desktopová kontrola jsou
  úspěšné; případná neprovedená kontrola zůstane výslovně otevřená.
