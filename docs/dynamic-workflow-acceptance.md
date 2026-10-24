<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Akceptace dynamického workflow

Tento checklist ověřuje `F-M4-DYNAMIC-WORKFLOW-01`. Používá pouze lokální
read-only analýzu; nemění projekt, nevolá externí provider a neověřuje ještě
konkrétní výzkumné fáze navazující dávky.

## Předpoklady

- Spusťte desktop nebo web z větve `feature/f-m4-dynamic-workflow-01` a
  otevřete testovací projekt.
- Poznamenejte si jeho HEAD a čistý `git status`.
- Otevřete **Creator → opponent → Řízená fronta**.

## Fyzický průchod

1. Rozbalte editor plánu a zvolte **Vložit dynamický read-only příklad**.
   JSON musí obsahovat plán verze 3, ruční režim, jedinou povolenou akci
   `analysis.read-only` a kumulativní limit jednoho kroku a jedné cost jednotky.
2. Stiskněte **Zkontrolovat návrh**. Vznikne pouze návrh revize 1. Zkontrolujte
   plán a aktivujte jej; aktivace nesmí sama provést krok.
3. Zvolte **Provést další krok**. Ruční režim musí nejprve přejít do
   `awaiting-approval`. Samostatně krok schvalte a znovu jej proveďte.
4. Karta musí zůstat aktivní a zobrazit revizi 1, dokončený krok a nulovou
   zbývající kapacitu. Další kliknutí nesmí plán implicitně dokončit.
5. V editoru revize zvolte **Přidat navazující krok** a odešlete návrh.
   Zobrazí se důvod, nový krok, změna limitu `1 → 2` a confirmation digest;
   druhý krok ještě nesmí vzniknout v aktivním plánu.
6. Restartujte aplikaci bez potvrzení. Návrh musí zůstat uložený, workflow
   zůstane bezpečně pozastavené a nic se samo nepotvrdí ani neprovede.
7. Znovu otevřete kartu. Teprve **Potvrdit přesnou revizi** po připojení živého
   UI smí atomicky vytvořit revizi 2, zvýšit limit a přidat druhý krok. Proveďte
   jej se samostatným schválením jako v bodu 3.
8. Zvolte **Zopakovat poslední krok**. Návrh musí použít nové step ID, uvést
   `repeat_of`, zvýšit limit na 3 a znovu vyžádat samostatné potvrzení revize.
   Po potvrzení a provedení zůstane původní krok i celá historie viditelná.
9. Zvolte **Ukončit plán**. `finish` nesmí přidat krok ani zvýšit limit; po
   aplikaci se workflow uzavře jako `completed` s auditovatelným důvodem.
10. Ověřte, že původní HEAD i `git status` testovacího projektu zůstaly stejné.

## Negativní a recovery hranice

- Pozměněný confirmation digest musí být odmítnut bez nové revize.
- Skryté nebo ztracené UI nesmí potvrdit zvýšení limitu ani spustit countdown.
- Změna projektového HEAD před návrhem či potvrzením revize musí tok zastavit.
- Neplatný následník, chybějící výstup, rozšíření permissions/privacy/boundary
  a stale souběžný návrh nesmí zanechat částečný krok ani historii.
- `dispatching → unknown` se po restartu nesmí opakovat. Doménový journal je
  jedinou autoritou účinku a projektový zápis stále vyžaduje vlastní přesné
  potvrzení.

## Automatické ověření

```sh
python3 -m unittest tests.test_action_autonomy tests.test_autonomy_service -v
python3 -m unittest discover -s tests -v
```

Před předáním navíc ověřte Python syntax, vygenerovaný JavaScript a
`git diff --check`. Fyzickou akceptaci nelze nahradit samotnými testy; její
výsledek se zapíše do `TODO.md` před uzavřením dávky.
