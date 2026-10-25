<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Fyzická akceptace telemetrie uzlu a runtime Ollamy

Tento průchod ověřuje `OPS-NODE-MONITOR-01` na skutečném desktopu a Ollama
endpointu. Diagnostika je pouze read-only: během akceptace automaticky
nerestartuje službu, nemění binding a neopakuje neznámý běh.

## Předpoklady

- Spusť desktop nad běžným node configem a otevři projekt i brainstormingové
  vlákno s potvrzeným Ollama bindingem.
- V Nastavení ověř přesný endpoint, model a boundary. Pro `private-network`
  ponech původní target ID a TLS pin.
- V panelu **Zdroje** nastav očekávaný runtime. Nastavení pouze popisuje
  očekávání; nezapíná GPU.

## Povinný průchod

1. Otevři **Zdroje**. Po prvním vzorku smějí CPU a NET hlásit čekání na druhý
   vzorek; do dalšího pollu musí přejít na hodnotu nebo explicitní `unknown`.
   RAM, disk a dostupná GPU/VRAM mají zdroj a čas měření. Zavření dialogu polling
   zastaví.
2. Odešli skutečný Ollama dotaz a počkej na finální odpověď. V právě dokončené
   odpovědi i přes tlačítko **Runtime běhu** ověř stejný historický procesor,
   poměr VRAM a čas. Změna živých ukazatelů nesmí tuto evidence přepsat.
3. Restartuj aplikaci. Očekávání i historická evidence stejného runu musí být
   znovu dostupné; živé CPU/NET začnou novým druhým vzorkem. Opětovné zobrazení
   historického runu nesmí volat model ani vytvářet další odpověď.
4. Pokud je dostupná GPU konfigurace, nastav očekávání `gpu` a ověř skutečný
   běh klasifikovaný `gpu` nebo pravdivě `partial-gpu`. Pokud lze bezpečně
   připravit CPU-only konfiguraci mimo Workspace, proveď nový běh: při doloženém
   `cpu` musí UI výrazně zobrazit `VAROVÁNÍ`. Workspace konfiguraci sám nemění.
5. Dočasně nedostupný `nvidia-smi`, chybějící model v `/api/ps` nebo opožděný
   druhý vzorek musí být `unknown`, nikoli 0 % a nikoli tvrzení o CPU běhu.
6. U existujícího `private-network` bindingu ověř, že evidence nese jeho přesné
   binding ID/revizi, boundary a target ID. Změněný certifikát či endpoint musí
   selhat stávající TLS/Target kontrolou; nesmí následovat fallback.

Scénář se označí jako ověřený jen tam, kde byla příslušná infrastruktura
skutečně dostupná. Nedostupný CPU-only, GPU nebo LAN scénář se zapíše jako
neověřený, nikoli jako úspěšný.

