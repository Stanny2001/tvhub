#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/Stanny2001/tvhub.git}"
TARGET_DIR="${TARGET_DIR:-/opt/tvhub}"
BRANCH="${BRANCH:-main}"

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  echo "Bitte als root ausführen." >&2
  exit 1
fi

pick_branch_with_installer() {
  git -C "$TARGET_DIR" for-each-ref --format='%(refname:short)' refs/remotes/origin \
    | sed 's#^origin/##' \
    | while read -r b; do
        git -C "$TARGET_DIR" ls-tree -r --name-only "origin/$b" -- setup.sh bootstrap.sh \
          | grep -Eq '^(setup.sh|bootstrap.sh)$' && { echo "$b"; break; }
      done
}

if [[ -d "$TARGET_DIR/.git" ]]; then
  echo "[bootstrap] bestehendes Repo gefunden: $TARGET_DIR"
  git -C "$TARGET_DIR" fetch --all --prune
  git -C "$TARGET_DIR" checkout "$BRANCH" || true
  git -C "$TARGET_DIR" reset --hard "origin/$BRANCH" || true
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

if [[ ! -x ./setup.sh && ! -x ./install.sh && ! -x ./scripts/install.sh ]]; then
  CANDIDATE="$(pick_branch_with_installer || true)"
  if [[ -n "$CANDIDATE" ]]; then
    echo "[bootstrap] Installer auf origin/$CANDIDATE gefunden, wechsle Branch."
    git -C "$TARGET_DIR" checkout "$CANDIDATE"
  fi
fi

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
