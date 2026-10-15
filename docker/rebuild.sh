#!/usr/bin/env bash
# Run from any directory; embed the actual checked-out source revision.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
SOURCE_COMMIT="$(git rev-parse HEAD)"
if [[ -n "$(git status --porcelain --untracked-files=normal)" ]]; then
    SOURCE_COMMIT="${SOURCE_COMMIT}-local"
fi
export SOURCE_COMMIT
docker compose build backend frontend
docker compose up -d --no-build
