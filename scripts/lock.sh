#!/usr/bin/env bash
# Regenerate the hash-locked requirements files from their sources.
#   bash scripts/lock.sh          # rewrite the locks (run after editing pyproject.toml)
#   bash scripts/lock.sh --check  # fail if the committed locks are stale (CI runs this)
#
# Needs uv (https://docs.astral.sh/uv/). Behind a TLS-intercepting proxy, set
# UV_SYSTEM_CERTS=1 so uv trusts the OS certificate store.
#
# --universal resolves for every platform, so one lock installs on Windows and Linux
# (platform-only deps like colorama and uvloop carry environment markers).
set -euo pipefail
cd "$(dirname "$0")/.."

compile() {
  uv pip compile --universal --python-version 3.11 --generate-hashes -q "$@"
}

# name -> "source output"
LOCKS=(
  "pyproject.toml --extra dev|requirements-dev.lock"
  "pyproject.toml|requirements.lock"
  "erp-agent-service/requirements.txt|erp-agent-service/requirements.lock"
)

if [[ "${1:-}" == "--check" ]]; then
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  stale=0
  i=0
  for entry in "${LOCKS[@]}"; do
    src="${entry%%|*}"; out="${entry##*|}"
    i=$((i + 1))
    # One output file per entry: uv reads an existing -o file as version preferences, so
    # reusing one path would leak the previous entry's pins into this one.
    # shellcheck disable=SC2086  # $src may carry flags ("--extra dev")
    compile $src -o "$tmp/$i.lock"
    # Header comments record the output path, so compare the pins only.
    if ! diff -q <(grep -v '^#' "$tmp/$i.lock") <(grep -v '^#' "$out") >/dev/null; then
      echo "stale: $out (run: bash scripts/lock.sh)"
      stale=1
    fi
  done
  [[ $stale -eq 0 ]] && echo "locks are up to date"
  exit $stale
fi

for entry in "${LOCKS[@]}"; do
  src="${entry%%|*}"; out="${entry##*|}"
  rm -f "$out" # start clean: uv would otherwise keep the old pins as preferences
  # shellcheck disable=SC2086
  compile $src -o "$out"
  echo "wrote $out"
done
