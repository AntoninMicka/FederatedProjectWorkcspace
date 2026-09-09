# Přispívání do projektu

Příspěvky do projektu jsou vítány.

## Licence příspěvků

Odesláním příspěvku do tohoto repozitáře potvrzujete, že máte právo
daný příspěvek poskytnout a že jej poskytujete pod podmínkami
Mozilla Public License 2.0 (MPL-2.0), která se vztahuje na tento projekt.

Samostatná Contributor License Agreement (CLA) není v současnosti
vyžadována.

## Před odesláním změny

- Respektujte existující architekturu a ADR projektu.
- Spusťte relevantní testy.
- Nezahrnujte credentials, API klíče ani jiné neveřejné informace.
- U významných architektonických změn nejprve popište návrh a jeho
  dopad na bezpečnost, federaci, datový model a kompatibilitu.
- U změn týkajících se LLM routingu, RBAC, provenance, federace,
  Context Manifestu nebo execution boundaries zvažte dopad na
  [Patent Risk Register](docs/IP/PATENT_RISK_REGISTER.md) a
  [defensive publication workflow](<docs/IP/IP, Defensive Publication & Crowdfunding Roadmap.md>).

## Third-party code

Do projektu nevkládejte kód nebo jiný obsah, jehož licence není
kompatibilní s MPL-2.0 nebo pro jehož použití nemáte potřebná práva.

Při přidání nové závislosti uveďte její licenci a případná omezení.

## Historie projektu

Významné technické změny mají být dohledatelné v Git historii,
dokumentaci a příslušných ADR. Projekt používá veřejnou historii
repozitáře také jako součást své defensive-publication strategie.
