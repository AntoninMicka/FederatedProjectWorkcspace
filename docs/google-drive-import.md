<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Google Drive import — konfigurace a fyzická akceptace

V Google Cloud Console povolte Google Drive API. Pro lokální aplikaci vytvořte
OAuth klienta typu **Desktop app**; Workspace pro něj používá Googlem
podporovanou loopback adresu `http://127.0.0.1:<náhodný-port>/`, kterou v
klientovi ručně neregistrujte. Pro server vytvořte samostatný klient typu
**Web application** a do `Authorized redirect URIs` vložte přesně
`<workspace HTTPS origin>/oauth/google-drive/callback`. Client ID a secret
správného klienta vložte v Nastavení → AI backend → Google Drive import.
Workspace žádá pouze `https://www.googleapis.com/auth/drive.file`.

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
