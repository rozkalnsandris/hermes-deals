#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
echo "== Git =="
git status --short
git log -5 --oneline 2>/dev/null || true
echo
echo "== Project manifests =="
find . -maxdepth 2 -type f \( -name 'pyproject.toml' -o -name 'requirements*.txt' -o -name 'compose*.yml' -o -name 'compose*.yaml' -o -name 'docker-compose*.yml' -o -name 'docker-compose*.yaml' -o -name 'alembic.ini' -o -name 'package.json' \) -print | sort
echo
echo "== Alembic migrations =="
find . -maxdepth 5 -type f -path '*/versions/*.py' -print 2>/dev/null | sort | tail -n 20 || true
echo
echo "== Recent evidence-like files =="
find . -type f \( -name '*.log' -o -name '*.json' \) -not -path './.git/*' -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -n 30 | cut -d' ' -f2-
