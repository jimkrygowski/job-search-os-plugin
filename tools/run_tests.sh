#!/bin/sh
set -e
cd "$(dirname "$0")/.."
python3 -m unittest discover -s tools -p 'test_*.py'

# Dashboard (TypeScript): type-check + node --test, then make sure the
# committed browser build matches a fresh one (users never build).
if ! command -v node >/dev/null 2>&1; then
  echo "FAIL: node (>= 22.18) is required to test the dashboard"; exit 1
fi
(
  cd dashboard
  [ -d node_modules ] || npm ci --silent --no-audit --no-fund
  npm test --silent
  fresh=$(mktemp -d)
  trap 'rm -rf "$fresh"' EXIT
  npx --no-install tsc -p tsconfig.web.json --outDir "$fresh"
  if ! diff -r "$fresh" web/dist >/dev/null; then
    echo "FAIL: dashboard/web/dist is stale — run 'npm run build' in dashboard/ and commit it"
    diff -r "$fresh" web/dist | head -20
    exit 1
  fi
)

# Static check: plugin content must not reference the old in-repo state/
# layout or call tools by a cwd-relative path.
bad=0
if grep -rnE '\bstate/(career|opportunity|tracker)|`state/`' skills commands guidance hooks; then
  echo "FAIL: state/ path references remain (above)"; bad=1
fi
if grep -rnE '\.claude/(skills|commands)|CLAUDE\.md|settings\.json' skills commands guidance; then
  echo "FAIL: references to the old repo layout remain (above)"; bad=1
fi
if grep -rnE 'tools/[a-z_]+\.py' skills commands guidance hooks | grep -v 'CLAUDE_PLUGIN_ROOT}/tools/'; then
  echo "FAIL: tool references without \${CLAUDE_PLUGIN_ROOT} (above)"; bad=1
fi
if grep -rnE 'node [^`]*dashboard/server/main\.ts' skills commands guidance hooks | grep -v 'CLAUDE_PLUGIN_ROOT}/dashboard/'; then
  echo "FAIL: dashboard server references without \${CLAUDE_PLUGIN_ROOT} (above)"; bad=1
fi
if grep -rnE '\bJim\b' skills commands guidance \
   || grep -nE '\b(his|he|him|himself)\b' skills/file-unemployment-claim/SKILL.md; then
  echo "FAIL: personal references remain (above)"; bad=1
fi
if git ls-files -z | xargs -0 grep -nI '/Users/[a-z]' 2>/dev/null; then
  echo "FAIL: absolute local home paths in tracked files (above)"; bad=1
fi
exit $bad
