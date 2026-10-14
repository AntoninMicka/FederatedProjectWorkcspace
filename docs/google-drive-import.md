<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Google Drive import — konfigurace a fyzická akceptace

V Google Cloud Console vytvořte OAuth klienta typu **Desktop app** pro lokální
desktop callback, nebo odpovídající webový klient pro přesnou HTTPS adresu
serveru. Povolte Google Drive API a do povoleného redirectu vložte přesně
`<workspace origin>/oauth/google-drive/callback`. Client ID a secret vložte v
Nastavení → AI backend → Google Drive import. Workspace žádá pouze
`https://www.googleapis.com/auth/drive.file`.

Akceptační průchod:

1. Otevřete projekt → Podklady → Importovat zdroj, nastavte privacy a otevřete
   Google Picker. Vyberte Markdown/PDF a jeden Google Doc, Sheet nebo Slide.
2. Vraťte se do workspace. Zkontrolujte seznam, revize, čas zdroje a explicitní
   PDF transformaci; před potvrzením nesmí v projektu vzniknout commit.
3. Potvrďte plán. Ověřte jediný nový commit, shodné blob bajty a SHA-256,
   exportní MIME provenance a oddělené `source_created_at`/`imported_at`.
4. Zopakujte stejnou revizi (musí být blokována), poté změněnou revizi (má
   navázat `supersedes`). Odvolejte přístup a ověřte selhání bez commitu.
5. Přerušte potvrzený download před publikací, restartujte aplikaci a použijte
   „Pokračovat v potvrzeném importu“. Musí vzniknout nejvýše jeden commit bez
   druhého downloadu již ověřeného stagingu.

Fyzická akceptace musí zvlášť zaznamenat desktopový i HTTPS webový průchod;
automatické testy s fake providerem nenahrazují skutečný účet a systémový
prohlížeč.
