<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — F-M3-OLLAMA-ROBUST-01: Odolnost lokálního AI běhu

Aktuální feature dávka **F-M3-OLLAMA-ROBUST-01 — Odolnost lokálního AI běhu**
vznikla 2026-10-10 na větvi `feature/f-m3-ollama-robust-01` z `develop`
`2c9b1b2` po začlenění UX-MOBILE-01 jako PR #49. Cíl PR je `develop`, PR zatím
nebyl vytvořen. Původ: nejbližší dávka BACKLOG a uživatelské upřesnění, že musí
obsahovat prakticky popsané a ověřitelné připojení k Ollama serveru v lokální
síti. Cílová úroveň: **PoC validated**.

Rozsah dávky: rozlišit nedostupnost Ollamy, timeout, přerušený transport,
odmítnutí TLS pinu, HTTP chybu, neplatnou JSON/strukturovanou odpověď a durable
`unknown`; nabídnout jen vědomý nový běh bez ztráty vstupního zadání a výběru
kontextu. Přidat vedené `private-network` připojení přes číselnou privátní HTTPS
adresu, stabilní target ID a připnutý certifikát. Beze změny zůstává zákaz
automatického retry neznámého účinku, skrytého fallbacku, odeslání `local-only`
mimo `same-node` a ukládání credentials do projektu nebo bindingu.

Persistentní a crash hranice: node-local `ollama-binding.json` zůstává jedinou
autoritou konfigurace a `ollama-runs.sqlite` autoritou stavu dispatchu. Před
prvním síťovým bajtem je durable `dispatching`; pád nebo nejistota po této
hranici končí `unknown` a původní run se nikdy znovu neposílá. Známé odmítnutí
před odesláním nebo validovaná HTTP/response chyba končí `failed`. Vědomý nový
pokus dostane nové run ID, ale znovu použije uživatelem zachované vstupy;
nevzniká projektový Git zápis ani distribuovaná transakce.

- [x] [completed] **F-M3-OLLAMA-ROBUST-01-A — Kontrakt chyb, LAN onboarding
  a reuse (cílová úroveň: designed).** Popsat podporovanou topologii Workspace →
  HTTPS reverse proxy → loopback Ollama, přesná pole bindingu, získání pinu,
  firewall a omezení současné autentizace. Vymezit známé `failed` proti
  `unknown`, obnovu po restartu a explicitní repin po rotaci certifikátu.
  Výsledek: `docs/ollama-lan.md`, ADR-0008 a reuse katalog popisují podporovanou
  topologii, trust boundary, crash hranice i vědomou rotaci pinu.
- [x] [completed] **F-M3-OLLAMA-ROBUST-01-B — Diagnostika transportu a healthcheck
  (cílová úroveň: implemented).** Zavést provider-neutral chybové kategorie pro
  nedostupnost, timeout, TLS/pin, HTTP, přerušenou/oversize odpověď a neplatný
  JSON či Ollama envelope. Read-only test bindingu nesmí odeslat projektová data,
  měnit potvrzený binding ani být vydáván za úspěšný generační běh.
  Výsledek: backend ukládá stabilní chybový kód a rozlišuje `failed`/`unknown`;
  kandidátní binding lze otestovat přes omezený `GET /api/tags` bez jeho uložení.
- [x] [completed] **F-M3-OLLAMA-ROBUST-01-C — Vědomý nový pokus a UI
  (cílová úroveň: implemented).** Zobrazit bezpečnou konkrétní diagnostiku,
  zachovat draft, výběr kontextu a existující externí preview a vytvořit nový
  run pouze po explicitní akci. Oddělit chybu lokálního/LAN Ollama routeru od
  chyby externího providera; nikdy nespouštět fallback automaticky.
  Výsledek: lokální workflow po známém i neznámém selhání zachová vstupy, zahodí
  pouze identitu neúspěšného requestu a další kliknutí vytvoří vědomě nový run;
  externí preview a externí provider zůstávají oddělené.
- [ ] [in progress] **F-M3-OLLAMA-ROBUST-01-D — Restart, souběh a závěrečná
  akceptace (cílová úroveň: PoC validated).** Ověřit pomalou odpověď, chybný
  JSON, chybějící model, chybný/rotovaný certifikát, pád před a po durable
  přechodu, restart aplikace/Ollamy, souběh, nový vědomý run a zákaz
  `local-only` na LAN. Spustit cílené testy, celou sadu a zkontrolovat
  dokumentaci, odkazy, finální diff a omezení skutečného LAN ověření.
  Automatizované ověření 2026-10-10: cílené testy transportu, desktopového UI,
  webového RBAC a balení prošly; úplná sada `python3 -m unittest discover -s
  tests -v` prošla 437 testy, 27 testů bylo záměrně přeskočeno kvůli chybějícímu
  nativnímu Qt/WebEngine či libgit2 prostředí. Živý read-only dotaz stejného uzlu
  na `http://127.0.0.1:11434/api/tags` prošel a našel nakonfigurovaný model.
  Zbývá provozní akceptace proti skutečnému druhému LAN stroji: HTTPS proxy,
  firewall, pin, generační běh a dostupnost po restartu Ollamy/stroje. Bez adresy
  a certifikátu cílového serveru tyto body nejsou ověřené a dávka není připravena
  k předání PR.

## K předání do backlogu

Zatím bez nových odkladů. Basic Auth nebo mTLS pro LAN proxy vyžadují samostatný
credential lifecycle; současný binding credentials záměrně nepřijímá a tato
dávka jej bez doložené potřeby nezavádí.

[Roadmapa](<Federovaný projektový LLM workspace – Master Checklist - základní roadmapa.md>) · [Backlog](BACKLOG.md) · [Historie](WORK_LOG.md) · [Pravidla](AGENTS.md)
