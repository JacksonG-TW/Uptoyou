#!/usr/bin/env bash
#
# Rebuild the five ER diagrams: live schema -> DDL -> Mermaid -> PNG.
#
#   docs/diagrams/build.sh            rebuild everything
#   docs/diagrams/build.sh --check    change nothing; exit non-zero if a committed file is stale
#
# Needs the stack up (`docker compose up -d --wait`) — the schema is read out of the running
# database, because this project has no ORM models for a generator to read (er_schema.py's
# docstring carries that whole argument). Both tools run in throwaway containers and neither
# is installed on this machine or baked into any image in the stack: erdify and mermaid-cli
# are documentation tools, not runtime dependencies.
#
# Every container is `--rm` and runs as the invoking user, so nothing is left behind and no
# output file arrives owned by root.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"   # app/docs/diagrams
APP="$(cd "$HERE/../.." && pwd)"                        # app/
DIAGRAMS=(er-overview er-reference er-weather er-product er-ledger)

# Pinned: an unpinned generator makes the drift check meaningless — it would report the
# tool's own version bump as a schema change.
ERDIFY_VERSION="0.12.1"
PYTHON_IMAGE="python:3.13-slim"
# mermaid-cli by version and digest: 11.16.0 is the release the committed PNGs were drawn
# with; re-rendered under this pin, four differ only in anti-aliasing and one not at all.
MERMAID_IMAGE="minlag/mermaid-cli:11.16.0@sha256:29077c6bd02f14bdfdd5fee552d9c00fe68d4fab3cd84952d21e2d1faf2fadaf"

CHECK=0
[ "${1:-}" = "--check" ] && CHECK=1

# --- 1. the live schema, reduced to what an ERD is made of ----------------------------
#
# pg_dump rather than the migrations: `alembic upgrade head --sql` replays the whole
# history, including its DROP CONSTRAINTs, so a parser reading it sees every table as it
# was first created rather than as it is.

dump_ddl() {  # $1 = output directory
  ( cd "$APP" && docker compose exec -T db sh -lc \
      'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --schema-only --no-owner --no-privileges' ) \
    | python3 "$HERE/er_schema.py" --out "$1"
}

# --- 2. Mermaid, by erdify ------------------------------------------------------------
#
# `--user` plus `HOME=/tmp` so `pip install --user` has somewhere to write and every file
# erdify creates belongs to the invoking user.

erdify_run() {  # $@ = extra erdify flags (e.g. --check)
  docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp \
    -v "$HERE:/w" -w /w "$PYTHON_IMAGE" sh -lc "
      set -e
      pip install --user -q --no-warn-script-location 'erdify[sql]==$ERDIFY_VERSION'
      export PATH=/tmp/.local/bin:\$PATH
      for name in ${DIAGRAMS[*]}; do
        erdify \"ddl/\$name.sql\" --sql-dialect postgres --format mermaid \
          -o \"\$name.mmd\" $*
      done
    "
}

# --- 3. PNG, by mermaid-cli -----------------------------------------------------------
#
# PUPPETEER_EXECUTABLE_PATH points at the image's own /usr/bin/chromium. Left at the
# default, puppeteer looks under $HOME for a browser it downloaded as uid 1001 and fails
# with a bare ENOENT that names neither the user nor the mount.
# -s 3 is the whole legibility setting: mermaid lays the diagram out at its natural size
# and this renders it at 3x, which is what makes the column names readable.

#
# The look comes from style.json, the same tokens the README pictures are drawn from:
# mermaid_theme.py maps them onto mermaid's `base` theme. The result is committed as
# er-theme.json, so --check can tell when a token change has left the PNGs behind.

render_png() {
  python3 "$HERE/mermaid_theme.py" "$HERE/style.json" > "$HERE/er-theme.json"
  for name in "${DIAGRAMS[@]}"; do
    docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp \
      -e PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium \
      -v "$HERE:/data" "$MERMAID_IMAGE" \
      -i "/data/$name.mmd" -o "/data/$name.png" -c /data/er-theme.json -b white -s 3
  done
}

if [ "$CHECK" = "1" ]; then
  temporary="$(mktemp -d)"
  trap 'rm -rf "$temporary"' EXIT
  dump_ddl "$temporary" >/dev/null
  failed=0
  for name in "${DIAGRAMS[@]}"; do
    if ! diff -q "$HERE/ddl/$name.sql" "$temporary/$name.sql" >/dev/null; then
      echo "stale: ddl/$name.sql no longer matches the live schema" >&2
      failed=1
    fi
  done
  # erdify's own drift check: does each .mmd still match what its .sql generates?
  erdify_run --check || failed=1
  # The theme: the PNGs were drawn with er-theme.json; does style.json still give the same?
  if ! python3 "$HERE/mermaid_theme.py" "$HERE/style.json" | diff -q - "$HERE/er-theme.json" >/dev/null; then
    echo "stale: er-theme.json no longer matches style.json, so the ER PNGs are drawn in an old look" >&2
    failed=1
  fi
  if [ "$failed" != "0" ]; then
    echo "" >&2
    echo "Rerun docs/diagrams/build.sh and commit the result." >&2
    exit 1
  fi
  echo "ER diagrams are current."
  exit 0
fi

dump_ddl "$HERE/ddl"
erdify_run
render_png
echo ""
echo "Rebuilt:"
for name in "${DIAGRAMS[@]}"; do
  echo "  $name.mmd  $name.png"
done
