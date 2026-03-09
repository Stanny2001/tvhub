#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

run() {
  local target="$1"
  if [[ -f "$target" ]]; then
    chmod +x "$target" || true
    echo "[pluto-gateway] starte installer: $target"
    exec "$target"
  fi
}

run "$ROOT_DIR/install.sh"
run "$ROOT_DIR/scripts/install.sh"

cat >&2 <<MSG
[pluto-gateway] FEHLER: Kein Installer gefunden.
Erwartet wurde eine der Dateien:
  - $ROOT_DIR/install.sh
  - $ROOT_DIR/scripts/install.sh

Bitte prüfen:
  1) Du bist im richtigen Repo-Ordner (pwd)
  2) Der Clone ist vollständig (git status, git branch -a)
  3) Optional neu klonen und direkt dieses Script aufrufen:
     cd /opt
     rm -rf tvhub
     git clone https://github.com/Stanny2001/tvhub.git
     cd tvhub
     ./bootstrap.sh
MSG
exit 1
