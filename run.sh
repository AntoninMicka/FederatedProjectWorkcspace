#!/usr/bin/env bash
# Launcher for Linux M0 storage and desktop experiments.
set -euo pipefail

usage() {
    cat <<'HELP'
Použití: ./run.sh [package-desktop [--output SOUBOR]|deploy-omnia USER@HOST [--container NAME] [--dry-run]|desktop|demo|setup|test|check CESTA|config project|node CESTA|help]

  deploy-omnia USER@HOST [--container NAME] [--dry-run]
               Ruční instalace headless PoC do běžícího Debian LXC na SSD.
  package-desktop [--output SOUBOR]  Sestaví zdrojový balíček desktopového PoC.
  desktop      Otevře Qt/WebEngine okno s lokálním testovacím backendem.
  demo         Ukázka Workspace v dočasném projektu (výchozí příkaz).
  setup        Vytvoří .venv a nainstaluje requirements.txt (vyžaduje pip/venv a síť).
  test         Spustí celou unittest sadu.
  check CESTA  Ověří artefakty a registry projektu bez zápisu; neověřuje project.json.
  config TYP CESTA  Ověří konfiguraci typu project nebo node bez zápisu.
  help         Zobrazí tuto nápovědu.

Desktop je PoC propojení UI/backendu bez ukládání projektů, LLM a federace.
Demo se po dokončení odstraní; nepracuje s vašimi projektovými daty.
Běžné spuštění nic nestahuje. Použije .venv/bin/python, jinak python3.
Desktop může použít systémový python3 s Qt a PyYAML, pokud Qt ve venv chybí.
HELP
}

command_name=${1:-demo}
case "$command_name" in
    help|-h|--help) usage; exit 0 ;;
    deploy-omnia|package-desktop) ;;
    desktop|demo|setup|test)
        if (( $# > 1 )); then usage >&2; exit 2; fi ;;
    check)
        if (( $# != 2 )); then usage >&2; exit 2; fi ;;
    config)
        if (( $# != 3 )) || [[ "$2" != project && "$2" != node ]]; then
            usage >&2; exit 2
        fi ;;
    *) printf 'Neznámý příkaz: %s\n' "$command_name" >&2; usage >&2; exit 2 ;;
esac

# Resolve caller-relative project paths before switching to the source directory.
if [[ "$command_name" == check || "$command_name" == config ]]; then
    if [[ "$command_name" == config ]]; then project_path=$3; else project_path=$2; fi
    if [[ "$project_path" != /* ]]; then project_path="$PWD/$project_path"; fi
fi
# Resolve package output relative to the caller before cd.
if [[ "$command_name" == package-desktop && $# == 3 && "$2" == --output && "$3" != /* ]]; then
    set -- "$1" "$2" "$PWD/$3"
fi
repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
cd -- "$repo_dir"
if [[ "$command_name" == package-desktop ]]; then
    shift
    exec python3 scripts/package_desktop.py "$@"
fi
if [[ "$command_name" == deploy-omnia ]]; then
    shift
    exec python3 scripts/deploy_omnia.py "$@"
fi
if [[ "$(uname -s)" != Linux ]]; then
    printf 'Tento PoC vyžaduje Linux.\n' >&2; exit 1
fi
if ! command -v git >/dev/null 2>&1; then
    printf 'Chybí Git v PATH.\n' >&2; exit 1
fi
python_bin=python3
if [[ -x "$repo_dir/.venv/bin/python" ]]; then python_bin="$repo_dir/.venv/bin/python"; fi
if ! command -v "$python_bin" >/dev/null 2>&1; then
    printf 'Chybí Python 3.11+. Nainstalujte jej včetně podpory venv.\n' >&2; exit 1
fi
if ! "$python_bin" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
    printf 'Je potřeba Python 3.11 nebo novější.\n' >&2; exit 1
fi

if [[ "$command_name" == setup ]]; then
    if [[ ! -x "$repo_dir/.venv/bin/python" ]]; then
        "$python_bin" -m venv "$repo_dir/.venv"
    fi
    exec "$repo_dir/.venv/bin/python" -m pip install -r "$repo_dir/requirements.txt"
fi
if ! "$python_bin" -c 'import yaml; assert yaml.__version__ == "6.0.3"' >/dev/null 2>&1; then
    printf 'Chybí požadovaný PyYAML 6.0.3. Spusťte: ./run.sh setup\n' >&2; exit 1
fi
# The desktop can use distro Qt without modifying an existing isolated venv.
if [[ "$command_name" == desktop ]]; then
    if ! "$python_bin" -c 'from PySide6.QtWebEngineWidgets import QWebEngineView' >/dev/null 2>&1; then
        if python3 -c 'from PySide6.QtWebEngineWidgets import QWebEngineView; import yaml; assert yaml.__version__ == "6.0.3"' >/dev/null 2>&1; then
            python_bin=python3
        else
            printf 'Chybí PySide6 WebEngine. Instalace desktopu je popsána v README.\n' >&2
            exit 1
        fi
    fi
    exec "$python_bin" -m spikes.desktop
fi
case "$command_name" in
    demo) exec "$python_bin" -m spikes.demo ;;
    test) exec "$python_bin" -m unittest discover -s tests -v ;;
    check) exec "$python_bin" -m spikes.check_project "$project_path" ;;
    config) exec "$python_bin" -m spikes.check_config "$2" "$project_path" ;;
esac
