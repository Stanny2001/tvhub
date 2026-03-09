#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/Stanny2001/tvhub.git}"
TARGET_DIR="${TARGET_DIR:-/opt/tvhub}"
BRANCH="${BRANCH:-main}"

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  echo "Bitte als root ausführen." >&2
  exit 1
fi

if [[ -d "$TARGET_DIR/.git" ]]; then
  echo "[bootstrap] bestehendes Repo gefunden: $TARGET_DIR"
  git -C "$TARGET_DIR" fetch --all --prune
  git -C "$TARGET_DIR" checkout "$BRANCH"
  git -C "$TARGET_DIR" reset --hard "origin/$BRANCH"
elif [[ -d "$TARGET_DIR" ]] && [[ -n "$(find "$TARGET_DIR" -mindepth 1 -maxdepth 1 2>/dev/null)" ]]; then
  cat >&2 <<MSG
[bootstrap] FEHLER: $TARGET_DIR existiert, ist aber kein Git-Checkout.
Lösung:
  rm -rf "$TARGET_DIR"
  git clone "$REPO_URL" "$TARGET_DIR"
MSG
  exit 1
else
  rm -rf "$TARGET_DIR"
  git clone "$REPO_URL" "$TARGET_DIR"
fi

cd "$TARGET_DIR"

if [[ -x ./setup.sh ]]; then
  exec ./setup.sh
elif [[ -x ./install.sh ]]; then
  exec ./install.sh
elif [[ -x ./scripts/install.sh ]]; then
  exec ./scripts/install.sh
else
  cat >&2 <<MSG
[bootstrap] FEHLER: Kein Installer gefunden in $TARGET_DIR.
Erwartet: setup.sh oder install.sh oder scripts/install.sh
MSG
  exit 1
fi
