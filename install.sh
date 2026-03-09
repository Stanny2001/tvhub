#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ ! -x "$SCRIPT_DIR/scripts/install.sh" ]]; then
  echo "ERROR: $SCRIPT_DIR/scripts/install.sh nicht gefunden oder nicht ausführbar." >&2
  echo "Prüfe, ob du im richtigen Repository-Ordner bist und ob der Clone vollständig ist." >&2
  exit 1
fi

exec "$SCRIPT_DIR/scripts/install.sh"
