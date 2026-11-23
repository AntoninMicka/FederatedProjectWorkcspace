<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0089 — Výslovná změna ochrany souboru a výjimka úpravy vstupu

Datum: 22. 11. 2026. Rozhodnutí vychází z výslovného požadavku uživatele
doplnit ochranu do všech editorů a umožnit konkrétní AI úpravu i přes konflikt
ochrany. Implementace a izolované ověření nejsou živou akceptací.

## Potřeba a rozhodnutí

Soubor měl klasifikaci v metadatech, ale běžný editor ji nemohl změnit.
Projektový seznam úkolů se proto nedal doplnit s důvěrnými podklady bez
jejich odebrání. Globální vypnutí privacy ani změna všech zdrojů nejsou
nutné k provedení požadované konkrétní operace.

Ochrana se zobrazuje a mění jako vlastnost **celého zdrojového souboru**,
společná pro strukturovaný, vizuální i Raw režim. Editor položky plánu
výslovně uvádí, že se volba týká i ostatních položek v témže souboru.
Julia editor používá jednu klasifikaci pro svůj existující čtyřsouborový
balík. Bez volby zůstává předchozí ochrana zachovaná; nový dokument má
výchozí `project`. `public`, `project`, `confidential`, `local-only`
zůstávají stejné třídy, nejde o novou sadu oprávnění.

Snížení klasifikace vyžaduje výslovné potvrzení uživatele a nativní
`authorize_privacy_relaxation: true` v přesném requestu. Bez něj kontrola
odmítne zápis. Na webu nelze vytvořit ani nastavit local-only soubor.
Změna ochrany nemaže starší verze Git, neodvolává dříve poskytnuté kopie
a není změnou členství nebo oprávnění projektu.

Konflikt mezi citlivějšími vstupy a méně chráněným cílem AI úpravy může
uživatel výslovně překonat volbou **Provést i přes omezení**. Souhlas platí
pro konkrétní zadání, revizi, cíl, výběr zdrojů, model a režim úpravy.
Před spuštěním se kontroluje otisk výběru; změna vstupů souhlas zneplatní.
Plán nese typovaný `privacy_override` se souhlasem a oběma klasifikacemi;
backend je ověří proti skutečně připravenému Context Manifestu a cíli.
Výjimka je součástí připnutého plánu, requestu, historie úlohy a otisku
finálního potvrzení. Vstupy i manifest si ponechají původní klasifikaci.
Výsledek lze uložit do cílové klasifikace až po samostatném potvrzení
diffu, který znovu ukáže výjimku a ochranu výsledku. Jde o výslovnou
reklasifikaci výsledku konkrétní operace, nikoli o přeznačení podkladů.

Výjimka se týká pouze lokálního file-edit průchodu s Ollamou. Nemění
kontrolu přístupu, read-only repliky, stale HEAD, validaci roadmapy,
externí execution kontrakty ani zákaz předávání local-only podkladů
externím providerům. Zúžení vstupů zůstává samostatnou volbou.

## Persistence, audit a obnova

Reuse: [ADR 0003](0003-coordinated-operation.md), původní
`Workspace.transact` a jeho `allow_privacy_relaxation`, editorové writery,
CAS, snapshot validace a [ADR 0088](0088-task-work-context.md).
Nevzniká nový store ani paralelní index. Obsah a metadata se mění v jedné
projektové transakci. Nativní request digest zahrnuje volbu a souhlas;
commit message zaznamená změnu klasifikace nebo výjimku kontextu a task ID.

- Před připravením journalu není souhlas uložením ani modelovým účinkem.
- Po připravení nativní operace obnovuje journal obsah a metadata společně,
  včetně původní autorizace snížení ochrany.
- Po Git commitu se obnoví index z HEAD. Ztracená odpověď se dokončí pod
  stejným operation ID; změněná volba ochrany pod tímto ID je odmítnuta.
- Před finálním potvrzením AI úpravy existuje pouze návrh. Po potvrzení
  zůstává původní task approval a nativní operace připnutá i po pádu.
  Obnova neopakuje model ani nepřenáší souhlas na jiný task.

## Ověření a meze

Testy ověřují neautorizované snížení, zachování klasifikace, replay, změnu
souhlasu pod stejným ID a procesové pády před/po commitu. Browser průchody
pokrývají plán v Raw režimu, editor položky a obě podoby prezentace; dále
zrušení výjimky, změnu zdrojů po odmítnutí a celé nové zpracování s původními
podklady až do potvrzeného zápisu. Model je lokální testovací náhrada.
Fyzický výpadek napájení ani živá akceptace uživatelského profilu nejsou
těmito testy doložené.
