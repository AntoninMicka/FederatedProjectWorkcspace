<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — UX-FEDERATION-02: plnohodnotná správa federace projektů

Původ: roadmapa M5, `F-M5-TRUST-01`, ADR 0021 a uživatelské upřesnění, že
servery v jedné schválené skupině mají projekty federovat automaticky a server
nasazený z desktopu nemá zůstat omezený na jednoho uživatele. Cílová úroveň:
**designed**. Větev: `feature/ux-federation-02`, základ/cíl PR: `develop`.

Tato dávka je záměrně návrhová. Vymezí společný model identit, skupin, politik,
autentizace a automatické replikace a rozdělí následnou implementaci na
reviewovatelné feature. Neimplementuje přihlášení, MFA, policy engine ani Git
synchronizaci a nemění běžící uzly.

## Úkoly dávky

- [ ] [in progress] **UX-FEDERATION-02-A — inventura a revize stávajících
  kontraktů (cílová úroveň: designed).** Porovnat ADR 0021, lokální účty,
  bearer přihlášení, portable ACL, peer trust, mapování a historický přenos
  M1-AH-14/15 s novým požadavkem. Výslovně nahradit osobní omezení serveru
  nasazeného desktopem bez ztráty auditovatelného původu uzlu.
- [ ] [planned] **UX-FEDERATION-02-B — identita, účty, skupiny a autentizace
  (cílová úroveň: designed).** Definovat lokální autoritu účtů, kvalifikované
  identity, lifecycle uživatele/skupiny/uzlu, plnohodnotné webové přihlášení,
  MFA a model jednoho aktivního uživatele desktopové instance nad více OS
  uživateli jednoho uzlu. Doplnit volitelnou centrální autoritu identity:
  oddělit adresář/provisioning uživatelů a skupin (např. LDAP/SCIM), ověření a
  assertions (např. OIDC) a lifecycle autentizátorů (WebAuthn/TOTP nebo služba
  IdP). Credentials, MFA secrets a session se nefederují ani nekopírují do
  projektových uzlů.
- [ ] [planned] **UX-FEDERATION-02-C — jednotný policy model
  (cílová úroveň: designed).** Jedním verzovaným a vysvětlitelným enginem
  vyhodnotit lokální ACL, export, příjem, další delegaci a automatickou
  replikaci, ale zachovat tyto účinky jako oddělené akce. Neznámá či konfliktní
  policy je fail-closed a `local-only` nikdy neopustí uzel.
- [ ] [planned] **UX-FEDERATION-02-D — automatická federace uvnitř skupiny
  (cílová úroveň: designed).** Oddělit organizační skupiny od replikačních sad,
  definovat podepsané členství, discovery, desired state, offline outbox/inbox,
  revokaci, konflikty, mazání, úplnost historie a audit bez předpokladu globální
  transakce nebo spolehlivých hodin.
- [ ] [planned] **UX-FEDERATION-02-E — threat model, migrace a implementační
  rozpad (cílová úroveň: designed).** Pokrýt bootstrap, rotaci/ztrátu klíčů,
  obnovu účtu a MFA, kompromitovaný uzel, stale členství, rolling upgrade,
  metadata leakage, kvóty a nouzové zastavení. Připravit migraci současných
  tokenů/registru a samostatné navazující dávky bez změny dat během návrhu.

## Akceptační podmínky

- pojmy uzel, lokální účet, kvalifikovaná identita, organizační skupina a
  replikační sada mají právě jednu autoritu a jednoznačný lifecycle;
- automatická replikace vzniká jen z ověřeného členství a explicitní policy,
  nikoli ze síťové dosažitelnosti nebo samotného názvu skupiny;
- efektivní práva jsou průnikem origin ACL, privacy, trust/scope, exportní a
  přijímací policy a lokálních práv; žádná vrstva je nesmí rozšířit;
- desktopový host je jeden uzel, ale každá instance jedná pouze za právě
  přihlášeného OS uživatele a nesdílí uživatelské credentials ani session;
- centrální služba identity je volitelná a identita se váže na stabilní
  dvojici autorita/subjekt; nedostupnost, změna skupiny a revokace mají
  explicitní offline/TTL a nouzový lokální recovery kontrakt;
- ADR, roadmapa a backlog popisují migraci i pořadí implementace bez tvrzení,
  že návrh už představuje funkční federaci nebo plnohodnotné přihlášení.
