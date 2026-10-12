<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Checklist streamované odpovědi Ollamy

Checklist ověřuje `F-M3-OLLAMA-STREAM-01` nad explicitně uloženým Ollama
bindingem. Použijte testovací projekt a neodesílejte citlivá data na LAN cíl,
dokud není ověřený HTTPS pin a síťová hranice.

## Běžný průchod

- [ ] Ukončete případný dříve spuštěný desktop a spusťte aktuální checkout přes
  `./run.sh desktop`. Již běžící proces si novou frontendovou implementaci
  nenačte.
- [ ] Spusťte desktop, otevřete projekt a v režimu **Brainstorming** vyberte
  **Ollama** a dostupný model.
- [ ] Odešlete prompt, který vygeneruje několik odstavců. UI má postupně ukázat
  přípravu kontextu, připojování, čekání na první část, případné
  **Ollama přemýšlí…** a generování. Interní reasoning text se nezobrazuje ani
  neukládá. Dokud nezačne odpověď, musí být vidět animovaný indikátor a
  průběžně rostoucí čas běhu přímo v historii zpráv nad composerem.
- [ ] Text se má objevovat průběžně, ale v seznamu zpráv vznikne assistant
  zpráva až po dokončení. Stručný stav je oznamovaný přes `aria-live`; samotné
  přibývající části textu se čtečce neoznamují po každém tokenu. Rozepsaná
  odpověď má při růstu zůstat ve viditelné části okna.
- [ ] Přepněte na **Orchestrace** a odešlete další úlohu. Ihned se musí objevit
  časovaný stav **Ollama zpracovává orchestraci…**. Task router nadále vrátí
  validovaný výsledek najednou; tento stav proto neoznačuje tokenový stream.
- [ ] Po dokončení porovnejte průběžný text s uloženou assistant zprávou a
  zkontrolujte providerem vrácené počty tokenů a časy, pokud je model poskytl.
- [ ] V bočním panelu otevřete **Chaty**. Nové vlákno musí být v části
  **Zařazené** a označené jako chat tohoto právě otevřeného projektu; nesmí
  skončit mezi nezařazenými chaty.
- [ ] U staršího vlákna v části **Nezařazené** otevřete nabídku `⋮`, zvolte
  **Zařadit do tohoto projektu** a ověřte jeho přesun do části **Zařazené**.
- [ ] Restartujte aplikaci. Dokončená zpráva musí zůstat ve vlákně a stejný
  dokončený run se nesmí znovu odeslat.

## Chybové a privacy hranice

- [ ] Přerušte spojení až po začátku generování. Částečný text musí zmizet,
  assistant zpráva nesmí vzniknout a běh musí zůstat `unknown`; další kliknutí
  smí vytvořit pouze vědomě nový run s novými ID.
- [ ] Ověřte nedostupný endpoint nebo odmítnutý request. Stav má být `failed`
  s bezpečnou diagnostikou a bez automatického fallbacku na jiný model či
  provider.
- [ ] U `private-network` bindingu ověřte správný TLS pin a odmítnutí
  `local-only`. Změna bindingu nebo jeho revize před dispatch se musí odmítnout.
- [ ] Režim **Orchestrace**, task router a creator/opponent workflow mají nadále
  používat svůj dosavadní celistvý providerový výsledek. Orchestrace během
  čekání ukazuje časovaný živý stav, ale není označena jako tokenový stream.

Automatická regrese pokrývá request digest, fragmentované NDJSON čtení, limity,
neplatný finální rámec, přerušení, restart bez retry, finální durable výsledek a
workspace NDJSON endpoint. Reálný model a fyzické přerušení zůstávají cílovou
akceptací podle tohoto checklistu.
