#!/bin/sh
# Pull the published commit and its published images, migrate, bring the stack up. The whole of
# D59's "CD pulls" on the box. It builds nothing: the images come from the registry.
#
#     app/deploy/pull-deploy.sh                    # what the timer runs
#     app/deploy/pull-deploy.sh --once             # same thing by hand, same output
#     app/deploy/pull-deploy.sh --rollback [<sha>] # by hand: back to an earlier recorded deploy
#     app/deploy/pull-deploy.sh --record           # by hand: record a hand-run deploy of HEAD
#     app/deploy/pull-deploy.sh --check-alert-channel
#
# **A bad deploy goes back by itself, within one schema (2026-11-16).** A deploy is bad when
# `up --wait` fails or times out (900 s), when /health through the proxy is not ok right after, or
# when the migration fails. On a bad deploy this script touches `.deploy-hold` first, so the next tick
# cannot retry the same commit, and then:
#   - the migration failed: nothing to undo (the whole upgrade is one transaction), so it alerts;
#   - the schema did not move: it returns to `.deployed-sha` without pulling, and alerts;
#   - the schema moved: it does NOT return, because the older api refuses a newer schema (exit 3),
#     and it alerts. The fix goes forward. Down-migrations are never run by any path here.
# The alert goes out through the `telegram_alerts` Connection inside the scheduler container. This
# script never reads the bot token.
#
# Exit codes: 0 deployed, or nothing to do · 2 unknown argument · 3 no flock · 4 git pull refused ·
# 5 the deploy changes the deploy (first run by hand) · 6 no alert channel · 7 no `.deployed-sha` ·
# 8 no image tagged with HEAD · 9 images never arrived · 10 `.deployed-sha` names an unknown commit ·
# 11 the migration failed, held, old version still serving · 12 bad deploy, rolled back, held ·
# 13 bad deploy, NOT rolled back, held · 14 `--rollback` or `--record` refused, nothing moved ·
# 15 this Docker Compose lacks `up --wait-timeout` or `up --pull`, nothing moved.
#
# **D59 says «CD pulls; nothing reaches into this VM». Until 2026-09-04 that was a stance with no
# mechanism** — there was no deploy script anywhere in the tree and nothing ran `git pull`. This is
# the mechanism. It is deliberately the smallest thing that can be correct.
#
# **Where it runs.** On the deployment box, inside a clone of the PUBLIC extract
# (github.com/JacksonG-TW/Uptoyou), which is `app/` and nothing else (D47). That repo is public, so
# the box holds no credential to read it — the only secrets on the box are in `.env`, which is not
# in any repo (H16).
#
# ---------------------------------------------------------------------------------------------
# **Three rules this script exists to get right, each one a hazard that has already bitten here.**
#
# **H28 — nothing is bind-mounted, so a `git pull` that changes source changes NOTHING until the
# images for that commit are pulled AND the containers recreated.** A stale image does not announce
# itself: every file on disk reads correct while the container serves last week's code. So this
# pulls the images tagged with the new commit before it ups, and ups with `--wait` so a container
# that will not come up is a failure here rather than a surprise later.
#
# **H64 in reverse, and this is the line somebody will "fix" — read before changing it.** No
# profile appears on this script's `pull` or `up`. A plain `docker compose pull` fetches every
# service that is not profile-gated — exactly the set this box runs — and leaves out `tests`, an
# image nobody will start on a 2 GB instance. **The `test` profile must never appear on the `up`**:
# `tests` is the one container holding the database owner's credential at rest (A15/D115), and
# starting it is what `split_boot_check.sh` asserts against.
#
# **A pull that changed nothing must do nothing.** Re-pulling and recreating on a timer when HEAD
# has not moved is how a box restarts itself in the middle of somebody's round for no reason.
# ---------------------------------------------------------------------------------------------

set -eu

HERE=$(cd "$(dirname "$0")" && pwd)      # <clone>/deploy
APP=$(cd "$HERE/.." && pwd)              # <clone>  — `app/`'s contents ARE the repo root here
LOCK=${DEPLOY_LOCK:-/tmp/upto-pull-deploy.lock}
say() { echo "$(date -u +%FT%TZ) pull-deploy: $*"; }

# **H100 — the alert channel is checked after every deploy, and its absence is a failed deploy.**
# `init.sh` creates `telegram_alerts` only when both `.env` names are set, and says nothing when
# they are not — right on a dev clone and in CI, wrong on the box, where it was silent for the whole
# launch. The check asks for the Connection by id through a hook that prints only the id (H99 —
# never the CLI's list, get or export forms, which print values); a missing id raises inside the
# container and the exec exits non-zero. Runs after `up --wait` on a deploy tick, and by hand as
# `pull-deploy.sh --check-alert-channel` (the same code, so a `.env` edit can be re-checked).
alert_channel_check() {
    if docker compose exec -T airflow-scheduler python -c \
        "from airflow.hooks.base import BaseHook as B; print(B.get_connection('telegram_alerts').conn_id)" \
        >/dev/null 2>&1; then
        say "alert channel: telegram_alerts present (checked by id only)"
        return 0
    fi
    say "ALERT CHANNEL: absent — no telegram_alerts Connection (or the scheduler could not be asked),"
    say "  so A10 sends nothing and a red task is reported to nobody. Presence, not delivery: a"
    say "  Connection with a wrong token passes. Set BOTH UPTO_TELEGRAM_BOT_TOKEN and UPTO_TELEGRAM_CHAT_ID in"
    say "  app/.env, then: docker compose up airflow-init --force-recreate --no-deps"
    say "  and re-check: $HERE/pull-deploy.sh --check-alert-channel   (H100)"
    return 6
}

# The database's own answer, or a word saying why there is none. **Never empty** — a blank in the
# deploy log reads as «it printed nothing», which is the state this is here to distinguish from.
_schema_revision() {
    found=$(docker compose exec -T db psql -U "${POSTGRES_USER:-upto}" -d "${POSTGRES_DB:-upto}" \
        -t -A -c 'select version_num from alembic_version' 2>/dev/null | tr -d ' \r\n') || found=""
    if [ -n "$found" ]; then echo "$found"; else echo "(could not be read)"; fi
}

UNREAD="(could not be read)"
WAIT_TIMEOUT=${DEPLOY_WAIT_TIMEOUT:-900}
if command -v timeout >/dev/null 2>&1; then BOUND="timeout 120"; else BOUND=""; fi

# **The alert, through the Connection Airflow already alerts with (owner 「A」, 2026-11-16).** The
# token stays where it is: inside the scheduler, read by the scheduler's own Python, used for one
# request and never printed. Nothing about the Connection is printed either (H99): the snippet
# marks its one-line outcome, and only that line is kept: Airflow logs to stdout, so everything
# else it prints is dropped (H110), and stderr goes to /dev/null. It is
# self-contained on purpose. After a rollback the scheduler running is the OLDER image, which may
# carry no helper of ours, and this has to work against it. The message is shas, revisions and
# exit codes, nothing secret, so it travels as an environment variable. **A failed send never fails
# the deploy path**: the journal line above it is the record that always exists, and when the
# stack is down, Airflow may be down too, so the journal line is all there is.
send_alert() {
    say "ALERT: $1"
    # **Only the line marked `OUTCOME` leaves the container** (measured in the dev drill,
    # 2026-11-16): Airflow logs to stdout, so a plain capture carried its «Connection Retrieved»
    # line into the journal and pushed the outcome off the alert line. What Airflow prints is not
    # this script's to decide, so nothing but the marked line is kept.
    sent=$($BOUND docker compose exec -T -e "UPTO_DEPLOY_ALERT=Up to you deploy: $1" \
        airflow-scheduler python - 2>/dev/null <<'PY' | sed -n 's/^OUTCOME //p' | tail -n 1
import json, os, sys, urllib.error, urllib.request
def out(line):
    print("OUTCOME " + line, flush=True)
try:
    from airflow.hooks.base import BaseHook
    c = BaseHook.get_connection("telegram_alerts")
except Exception as e:
    out("not sent: no telegram_alerts Connection ({})".format(type(e).__name__)); sys.exit(2)
token, chat = (c.password or "").strip(), (c.login or "").strip()
if not token or not chat:
    out("not sent: the Connection lacks its token or chat id"); sys.exit(2)
body = json.dumps({"chat_id": chat, "text": os.environ.get("UPTO_DEPLOY_ALERT", "")}).encode()
req = urllib.request.Request("https://api.telegram.org/bot{}/sendMessage".format(token), data=body,
                             headers={"Content-Type": "application/json"}, method="POST")
try:
    with urllib.request.urlopen(req, timeout=20) as r:
        out("sent (HTTP {})".format(r.status))
except urllib.error.HTTPError as e:
    out("not sent: Telegram refused it (HTTP {})".format(e.code)); sys.exit(3)
except Exception as e:
    out("not sent: {}".format(type(e).__name__)); sys.exit(3)
PY
    ) || true
    say "  alert: ${sent:-not sent: the scheduler could not be asked}"
}

# **/health through the proxy, as a member reaches it** (Q1's second half). Asked inside the proxy
# container on its own listener, so the check is the same on the box, a dev VM and the drill
# whatever ports they publish. Three tries, five seconds apart: `--wait` has just seen every
# healthcheck pass, so this is a confirmation, not a second clock.
proxy_health_ok() {
    for try in 1 2 3; do
        answer=$(docker compose exec -T proxy wget -q -O - http://127.0.0.1:8080/health 2>/dev/null) || answer=""
        case "$answer" in *'"status":"ok"'*) say "health through the proxy: ok"; return 0 ;; esac
        [ "$try" = 3 ] || sleep "${DEPLOY_HEALTH_PAUSE:-5}"
    done
    say "health through the proxy: ${answer:-no answer}"
    return 1
}

# Every image the compose file names at tag $1 is on this disk. Sets `absent` for the message.
images_on_disk() {
    absent=""
    refs=$(UPTO_IMAGE_TAG="$1" docker compose config --images 2>/dev/null | grep ":$1\$" | sort -u) || refs=""
    [ -n "$refs" ] || { absent=" (no image in the compose file is tagged $1)"; return 1; }
    for ref in $refs; do
        docker image inspect "$ref" >/dev/null 2>&1 || absent="$absent $ref"
    done
    [ -z "$absent" ]
}

# **The two flags the rollback stands on, asked for before anything moves.** The box ran Compose
# v2.29.7 on 2026-11-16, and both flags are in that version's own source (`cmd/compose/up.go`:
# `--pull` at line 144, `--wait-timeout` at line 165, in seconds at line 294; read 2026-11-16 at
# github.com/docker/compose, tag v2.29.7). An older Compose would reject the flag only at the `up`,
# halfway through a deploy, and then reject it again on the way back. So a Compose without them is
# refused here, with nothing pulled and nothing restarted.
compose_flags_ok() {
    help=$(docker compose up --help 2>/dev/null) || help=""
    for flag in --wait-timeout --pull; do
        case "$help" in *"$flag"*) ;; *)
            say "REFUSING: this Docker Compose has no \`up $flag\`, which the rollback needs. Nothing was pulled or restarted."
            say "          Upgrade docker-compose-plugin (v2.29.7 has both), then the next tick deploys."
            return 1 ;;
        esac
    done
}

# **`.deployed-history`: one line per deploy that passed, never rewritten (owner 「A」, 2026-11-16).**
# `<UTC time> <full sha> <schema revision> <how>`, where <how> is `deploy` (a tick), `rollback`
# (this script went back by itself), `hand-rollback` or `hand` (a person's `--rollback`/`--record`).
# A schema that could not be read is written as one word, so every line keeps its four fields
# (the reviewer, 2026-11-16). It can never equal a real revision, so `--rollback` refuses it.
history_append() {
    schema=$2
    [ "$schema" != "$UNREAD" ] || schema=unread
    printf '%s %s %s %s\n' "$(date -u +%FT%TZ)" "$1" "$schema" "$3" >> "$HISTORY"
}

# The brake, with its reason in it, so `cat .deploy-hold` says why the box is standing still.
hold_because() {
    printf '%s %s\n' "$(date -u +%FT%TZ)" "$1" > "$HOLD"
    say "HELD: wrote $HOLD ($1). Every tick does nothing until a person removes it."
}

# Up at tag $1 without pulling, then /health through the proxy. The return path of both the
# automatic rollback and `--rollback`. `--pull never` (Q4): a pull during an outage on a nearly full
# disk is a second failure, so the caller has already checked that the images are on disk.
return_to() {
    UPTO_IMAGE_TAG="$1"
    export UPTO_IMAGE_TAG
    say "returning to $1 (up --wait --wait-timeout $WAIT_TIMEOUT --pull never)"
    t0=$(date +%s)
    if docker compose up -d --wait --wait-timeout "$WAIT_TIMEOUT" --pull never && proxy_health_ok; then
        say "back at $1 after $(( $(date +%s) - t0 ))s"
        return 0
    fi
    say "the return to $1 FAILED after $(( $(date +%s) - t0 ))s"
    return 1
}

short() { printf '%.12s' "$1"; }

# **One at a time.** A pull plus a migration on a small instance can outlast the timer's period;
# two overlapping runs would fight over the image tags and the containers. `flock` is in util-linux
# and is on the AMI; if it is ever absent this exits rather than running unguarded. The hand-run
# form: only the check, no pull, no build, no lock (it reads, it does not deploy).
if [ "${1:-}" = "--check-alert-channel" ]; then
    cd "$APP"
    alert_channel_check
    exit $?
fi
MODE=tick
TARGET=""
case "${1:-}" in
    ""|--once) ;;
    --rollback) MODE=rollback; TARGET=${2:-} ;;
    --record) MODE=record ;;
    *) say "unknown argument: $1 (see the usage at the top of $0)"; exit 2 ;;
esac

if command -v flock >/dev/null 2>&1; then
    exec 9>"$LOCK"
    flock -n 9 || { say "another run holds $LOCK — skipping this tick"; exit 0; }
else
    say "flock not found; refusing to run unguarded"; exit 3
fi

cd "$APP"

# **What is deployed, recorded — not inferred from whether a pull moved HEAD** (2026-10-08). Until
# this file existed the script deployed «if `git pull` moved HEAD». Publishing put the code first
# and the images after it (since 2026-10-10 the repository's own workflow builds them on each push), so a tick landing between them pulled the commit, failed `compose pull`
# («manifest unknown») and exited — and every later tick saw HEAD unmoved and said «no change» for
# ever. A failed `migrate` stranded a commit the same way. H83's shape: the clone moved, the stack
# did not, and nothing said so. Now the clone's position and the stack's position are two facts:
# `.deployed-sha` is written only after `up --wait` and the alert-channel check succeed, and every
# tick compares HEAD against it. Anything that stops short leaves it alone, so the next tick retries.
STATE="$APP/.deployed-sha"
HOLD="$APP/.deploy-hold"
HISTORY="$APP/.deployed-history"

# **`--record`: the last step of a hand-run deploy (H85's exit 5).** Only this script writes
# `.deployed-history`, so a person's deploy is recorded through it too. It records HEAD only after
# checking that what runs IS HEAD (every service's image carries HEAD's tag, H28), that /health
# through the proxy is ok, and that the alert channel exists, the same bar a tick's deploy meets.
if [ "$MODE" = record ]; then
    head=$(git rev-parse HEAD)
    for svc in api proxy airflow-scheduler; do
        cid=$(docker compose ps -q "$svc" 2>/dev/null) || cid=""
        image=""
        [ -z "$cid" ] || image=$(docker inspect --format '{{.Config.Image}}' "$cid" 2>/dev/null) || image=""
        case "$image" in *":$head") ;; *)
            say "REFUSING to record: $svc runs '${image:-nothing}', not HEAD $head. Nothing was written."
            exit 14 ;;
        esac
    done
    proxy_health_ok || { say "REFUSING to record: the stack is not serving. Nothing was written."; exit 14; }
    alert_channel_check || exit $?
    printf '%s\n' "$head" > "$STATE.tmp" && mv "$STATE.tmp" "$STATE"
    history_append "$head" "$(_schema_revision)" hand
    say "recorded $head in $STATE and $HISTORY"
    exit 0
fi

# **`--rollback [<sha>]`: a person going back on 「跑」** (owner 「A」, 2026-11-16). The same return
# path the automatic rollback takes. Without a sha it goes to the newest line in `.deployed-history`
# that is not what serves now. Every refusal below moves nothing (exit 14). It holds the timer
# first, because otherwise the next tick would deploy HEAD straight back; a person removes the hold
# to roll forward. It goes back only to a recorded deploy, only where the compose file and
# `airflow/init.sh` are the same as HEAD's (this compose file is what will run), and only at the
# schema the database is at now.
if [ "$MODE" = rollback ]; then
    [ -s "$STATE" ] || { say "REFUSING: $STATE is missing — what is serving is not recorded."; exit 7; }
    # Asked here as on a tick (the reviewer, 2026-11-16): without it, an old Compose would get the
    # hold written, refuse the flag at the `up`, and the alert would say «not serving» while the old
    # stack still served.
    compose_flags_ok || exit 15
    deployed=$(tr -d ' \r\n' < "$STATE")
    [ -s "$HISTORY" ] || { say "REFUSING: $HISTORY is empty — no earlier deploy is recorded to go back to."; exit 14; }
    if [ -z "$TARGET" ]; then
        TARGET=$(awk -v now="$deployed" '$2 != now { t = $2 } END { print t }' "$HISTORY")
        [ -n "$TARGET" ] || { say "REFUSING: $HISTORY records no deploy other than $deployed."; exit 14; }
    fi
    line=$(awk -v t="$TARGET" '$2 == t { l = $0 } END { print l }' "$HISTORY")
    [ -n "$line" ] || { say "REFUSING: $TARGET is not in $HISTORY — only a recorded deploy is gone back to (a full sha)."; exit 14; }
    # The target may be `.deployed-sha` itself, on purpose: after an exit 13 the record still names
    # the last good sha while a broken one runs, and bringing the recorded one back up is the repair.
    git cat-file -e "$TARGET^{commit}" 2>/dev/null || { say "REFUSING: this clone does not have $TARGET."; exit 14; }
    if ! git diff --quiet "$TARGET" HEAD -- compose.yaml airflow/init.sh; then
        say "REFUSING: compose.yaml or airflow/init.sh differs between $TARGET and HEAD, so going back"
        say "          with this clone's files would run a mix that no commit describes."
        exit 14
    fi
    then_schema=$(printf '%s\n' "$line" | awk '{ print $3 }')
    now_schema=$(_schema_revision)
    if [ "$now_schema" = "$UNREAD" ] || [ "$then_schema" != "$now_schema" ]; then
        say "REFUSING: $TARGET ran at schema $then_schema and the database is at $now_schema; the older api"
        say "          refuses a schema that is not its own (exit 3). Fix forward instead."
        exit 14
    fi
    if ! images_on_disk "$TARGET"; then
        say "REFUSING: images for $TARGET are not on this disk:$absent"
        say "          Nothing was pulled. A person may pull them first, then run this again."
        exit 14
    fi
    hold_because "hand rollback from $deployed to $TARGET"
    if return_to "$TARGET"; then
        printf '%s\n' "$TARGET" > "$STATE.tmp" && mv "$STATE.tmp" "$STATE"
        history_append "$TARGET" "$now_schema" hand-rollback
        send_alert "rolled back by hand from $(short "$deployed") to $(short "$TARGET"), schema $now_schema. Timer held: remove $HOLD to roll forward."
        exit 0
    fi
    send_alert "the hand rollback from $(short "$deployed") to $(short "$TARGET") FAILED: not serving. Timer held."
    exit 13
fi

# **The brake.** A person rolling back by hand, or holding the box still for any reason, touches this
# file; the timer then does nothing — not even a fetch — until it is removed.
if [ -e "$HOLD" ]; then
    say "HOLD: $HOLD exists — doing nothing this tick (remove it to resume)"
    exit 0
fi

# **No record, no guess.** Without `.deployed-sha` this cannot know what is serving, and deploying
# «whatever HEAD is» could be deploying nothing new or skipping a migration. A person records it once.
if [ ! -s "$STATE" ]; then
    say "REFUSING: $STATE is missing — what is serving is not recorded."
    say "          If the stack runs exactly this clone's HEAD, record it:  $HERE/pull-deploy.sh --record"
    exit 7
fi
deployed=$(tr -d ' \r\n' < "$STATE")

say "deployed $deployed, fetching"
# **`--ff-only`.** A clone that has diverged — somebody edited a file on the box — must STOP, not
# merge. A merge commit created by a timer at 04:00 is a state nobody can reason about afterwards.
if ! git pull --ff-only --quiet; then
    # **Single quotes, and this line has already bitten.** In double quotes the backticks around
    # the command name were COMMAND SUBSTITUTION: the failure message re-ran `git pull --ff-only`,
    # which is why the hint block printed twice the first time this path was exercised. Harmless
    # for a pull; not harmless as a habit in a script that also migrates and restarts things.
    say 'REFUSED: git pull --ff-only failed. The clone has diverged or the remote is unreachable.'
    say "         Nothing was built and nothing was restarted. Look before forcing anything."
    exit 4
fi
after=$(git rev-parse HEAD)

# **A box that is AHEAD of its remote is running code that is in no repository — say so.**
# Found while testing this script: `--ff-only` only refuses when the remote has ALSO moved. A
# local commit made on the box (an edit, a "quick fix") leaves HEAD ahead, the pull succeeds
# trivially, and the box serves something nobody can look up. That is H28's family — the served
# thing is not the named thing — and the only difference here is that the artefact reading correct
# is `git log` on somebody else's machine.
upstream=$(git rev-parse --abbrev-ref '@{u}' 2>/dev/null || echo "")
if [ -n "$upstream" ] && ! git merge-base --is-ancestor "$after" "$upstream"; then
    say "WARNING: HEAD is AHEAD of $upstream — this box holds commit(s) that are in no repository:"
    git --no-pager log --oneline "$upstream..$after" | sed 's/^/    /'
    say "         Deploying anyway (the box keeps serving), but what runs here cannot be looked"
    say "         up from the repository until these are pushed or dropped."
fi

if [ "$deployed" = "$after" ]; then
    say "no change at $after — nothing to do"
    exit 0
fi

# **A recorded sha this clone does not have is named, not misread** (the reviewer's catch,
# 2026-10-08). `git diff` against an unknown commit exits 128, which the `deploy/` check below
# would read as «the deploy changed» — a refusal with the wrong cause.
if ! git cat-file -e "$deployed^{commit}" 2>/dev/null; then
    say "REFUSING: $STATE holds $deployed, a commit this clone does not have."
    say "          Record what is actually serving (git rev-parse HEAD > $STATE if it is HEAD)."
    exit 10
fi

say "deployed $deployed, clone at $after"
git --no-pager log --oneline "$deployed..$after" 2>/dev/null | sed 's/^/    /' || true

# **⚠️ THE SCRIPT RUNNING IS THE ONE FROM BEFORE THE PULL — H85, measured 2026-09-11.** The shell
# read this file at exec time; `git pull` has just replaced it on disk, and nothing re-reads it. So
# a deploy that changes the deploy's own steps runs the OLD steps against the NEW compose file, and
# **the script cannot warn about a step it does not yet have**.
#
# That is not hypothetical: candidate 14's copy of this file had no `run --rm migrate` step,
# because on 14 the schema ran inside `up`. It pulled 15+16+17, whose compose puts `migrate` behind
# the bootstrap profile, so `up` started no migrate, the database stayed one revision back, the new
# api's startup guard exited 3 on every restart exactly as designed, and the proxy waited on an api
# that never came up. **Ten minutes of 521 from a correct guard doing its job**, because the thing
# that should have migrated was a step in a file that had not run yet.
#
# **So this refuses rather than deploying half a boot — and since 2026-10-08 it refuses on EVERY
# tick**, because it compares against what is deployed, not against where the clone was a moment
# ago. It used to refuse once and then fall silent (the clone had moved, so the next tick saw «no
# change»). The hand-run ends by recording the new state, and the tick after that is normal.
#
# **Rejected: re-exec'ing from the pulled file.** It fixes this case and opens a worse one — a
# pulled script with a bug takes out the deploy path itself, and D59 leaves this box no other way
# in. A refusal keeps the box serving what it has and asks for a person; a bad re-exec leaves
# nothing running and nobody able to reach it.
#
# **`compose.yaml` is held the same way (owner 「A」, 2026-10-10).** It reaches the box without an
# image: a pushed change to a mount, a privilege, an image name or the migrate command would be
# applied by `pull`, `migrate` (as the database owner) and `up` below with no person looking — and
# this service runs with Docker, which is root-equivalent. So its first deploy is by hand too.
# **`airflow/init.sh` likewise (owner 「加」, 2026-10-10):** compose mounts it from this clone and
# runs it as airflow-init's entrypoint on every `up`, with Airflow's database credentials — the same
# reach, and no image in between. (db/init runs only on an empty volume; tls/ holds no file.)
# **Except `deploy/*.md` (owner 「改」, 2026-10-10).** Prose reaches the box as a file nothing runs, so
# a README-only release deploys on its own; the first one cost a hand-run for a change of words. Any
# other file in `deploy/` — the script, its units — is still held, and so is a release that changes
# a README *and* one of them. The pathspecs are written out, quoted, rather than kept in a variable:
# this is POSIX sh, and an unquoted `*.md` would be a filename glob before git ever saw it.
held_diff() {
    git "$@" "$deployed" "$after" -- deploy/ ':(exclude)deploy/*.md' compose.yaml airflow/init.sh
}
if ! held_diff diff --quiet; then
    say "REFUSING: this deploy changes the deploy itself (deploy/ other than its .md files, compose.yaml or airflow/init.sh)."
    held_diff --no-pager diff --stat | sed 's/^/    /'
    say "         A compose.yaml or airflow/init.sh change reaches the box without an image, so a person looks first."
    say "         A deploy/ change: the script that just ran is the one from before the pull — it cannot perform a"
    say "         step it does not have. Nothing was pulled into the stack and nothing was restarted,"
    say "         and every tick will say this until a person runs the new file's steps (H85):"
    say "             cd $APP && export UPTO_IMAGE_TAG=$after \\"
    say "               && docker compose pull --quiet && docker compose run --rm migrate \\"
    say "               && docker compose up -d --wait --wait-timeout $WAIT_TIMEOUT \\"
    say "               && $HERE/pull-deploy.sh --record"
    exit 5
fi

# **This box does not build, and that is the point** (owner 「公開」 2026-09-07; the registry research
# preceded it). It built its own images until then, and on
# 2026-09-05 that wedged it for twelve hours — `npm ci` and a Vite build on a swapless 2 GB instance
# with the stack running (H76's neighbour). The images are built off the box — since
# 2026-10-10 by this repository's own workflow (`.github/workflows/cd.yml`), on each push — and
# pushed to GHCR as PUBLIC packages, so this pull needs **no credential**: «You can also access
# public container images anonymously» (GitHub, read 2026-09-07). What arrives is named by the
# extract's own commit, so «what is this running» is answerable from a repository anybody can fetch.
#
# **A pull is I/O, not memory**, so the failure this replaces is gone rather than mitigated, and the
# stack keeps serving until the recreate — the outage window is a container restart instead of a
# frontend build. `.env` carries `UPTO_IMAGE_PREFIX=ghcr.io/jacksong-tw/upto-`; the tag is derived
# below from the commit this clone just moved to. **A rollback holds the timer first**, or the
# next tick would pull main again: the automatic one below and `--rollback` both do. Either goes
# back only within one schema, because migrations are forward-only and an older api refuses a newer
# schema. Across a migration the fix goes forward: revert or fix on main, publish, remove the hold.
# **The tag IS the commit this clone just moved to, and that dissolves a trade** (ruled
# 2026-09-07). The alternative shapes were: follow `:latest` and inherit H28 one layer up — a tag
# that resolves to something different each day is the stale image that does not announce itself —
# or pin a sha by hand in `.env`, which is a person editing a file on every deploy. This clone IS
# the public extract, so the commit it is standing on is exactly the sha the workflow tagged
# with. No edit, no moving tag, and **a missing image for this sha fails the pull loudly**, which is
# the failure we want: the box refuses to start something nobody published rather than quietly
# serving whatever `:latest` last pointed at. `:latest` still exists in the registry as a human
# convenience; nothing here reads it.
UPTO_IMAGE_TAG="$after"
export UPTO_IMAGE_TAG

# **Deploy only what has been published — wait, rather than fail, for images that are not there
# yet** (2026-10-08). The code reaches the public repository a minute or more before its images
# reach the registry, so a tick in between finds a commit with no images. That is not a fault: it
# exits 0 with the state untouched and the next tick asks again. The names are compose's own
# (`config --images` with the tag set), the tag is the full commit — the string the workflow
# pushes (H103) — and the registry is asked anonymously, like the pull itself.
anon=$(mktemp -d)
missing=""
for ref in $(docker compose config --images 2>/dev/null | grep ":$after\$" | sort -u); do
    DOCKER_CONFIG="$anon" docker manifest inspect "$ref" >/dev/null 2>&1 || missing="$missing $ref"
done
rm -rf "$anon"
if [ -z "$(docker compose config --images 2>/dev/null | grep ":$after\$")" ]; then
    say "REFUSING: no image in the compose file is tagged $after — is UPTO_IMAGE_PREFIX set in .env?"
    exit 8
fi
# **Waiting is bounded** (the reviewer's catch, 2026-10-08): an image push that failed would
# otherwise read as «waiting» with exit 0 for ever. The clock is when THIS script first saw the
# commit waiting — not the commit's own date, which the extract keeps from when it was written,
# often hours before it was published. After an hour it says so with a non-zero exit, so
# `systemctl --failed` and the journal show it; it still deploys the moment the images arrive.
WAITING="$APP/.waiting-since"
if [ -n "$missing" ]; then
    now=$(date +%s)
    since=""
    if [ -s "$WAITING" ] && [ "$(cut -d' ' -f1 "$WAITING")" = "$after" ]; then
        since=$(cut -d' ' -f2 "$WAITING")
    else
        printf '%s %s\n' "$after" "$now" > "$WAITING"
        since=$now
    fi
    waited=$(( now - since ))
    say "waiting for images at $after (${waited}s so far) — not in the registry yet:$missing"
    say "  nothing pulled, nothing restarted; the next tick asks again"
    limit=${DEPLOY_IMAGE_WAIT_LIMIT:-3600}
    if [ "$waited" -gt "$limit" ]; then
        say "FAILED: still no images ${waited}s after this commit was first seen (limit ${limit}s) — did the repository's image workflow finish for it?"
        exit 9
    fi
    exit 0
fi
rm -f "$WAITING"

compose_flags_ok || exit 15

say "pulling images at $after"
docker compose pull --quiet

# **The schema, once per version, before anything starts on the new code** (owner 「一次」,
# 2026-09-11). It used to be a service every instance ran at boot; with more than one instance that
# is N migrations racing one database. `run --rm` on the `bootstrap` profile is one container that
# exits, and a failed migration stops this deploy here: it holds and alerts (below), nothing is
# recreated, and the box keeps serving the version it has. `alembic upgrade head` is idempotent, so on a deploy
# that changed no schema this prints its two lines and costs a few seconds.
# **The revision is said out loud, before and after.** It scrolled out of the log during the
# 2026-09-11 incident and the one question nobody could answer from the tail was «did the schema
# move». A deploy log that does not name the revision cannot tell a migration that ran from one
# that was never started.
#
# **A failed migration holds (owner 「A」, 2026-11-16).** It used to stop here and leave the next
# tick to retry it every five minutes, with nobody told. `env.py` runs the whole upgrade inside one
# transaction and Postgres DDL is transactional, so a failed migrate changes nothing and the old
# stack keeps serving: there is nothing to roll back, only a person to tell. The revision is read
# again rather than assumed, so a migration that left the schema moved anyway is named as that.
say "applying migrations (once, before the stack moves)"
schema_before=$(_schema_revision)
say "  schema before: $schema_before"
if ! docker compose run --rm migrate; then
    schema_now=$(_schema_revision)
    say "  schema after the failed migration: $schema_now"
    hold_because "the migration to $after failed"
    if [ "$schema_now" = "$schema_before" ] && [ "$schema_now" != "$UNREAD" ]; then
        send_alert "the migration to $(short "$after") failed and the database undid it (schema $schema_before unchanged). Still serving $(short "$deployed"); nothing was restarted. Timer held: remove $HOLD after the fix."
    else
        send_alert "the migration to $(short "$after") failed and the schema reads $schema_now (was $schema_before). Read the migrate log before anything else. Nothing was restarted. Timer held."
    fi
    exit 11
fi
schema_after=$(_schema_revision)
say "  schema after:  $schema_after"

# **`--wait` is the difference between deploying and hoping.** Without it `up -d` returns as soon
# as the containers are created, and a container that dies on its healthcheck is discovered by a
# member instead of by this script. `up` never migrates: the migration ran once, above.
# **Bounded at 900 s (owner, 2026-11-15):** about twice the slowest deploy measured on the box
# (421–459 s for this step), so a deploy that hangs is called bad instead of waited on for ever.
say "starting"
t0=$(date +%s)
if docker compose up -d --wait --wait-timeout "$WAIT_TIMEOUT" && proxy_health_ok; then
    say "UP at $after after $(( $(date +%s) - t0 ))s"
    # The stack is serving; a missing alert channel is still a failed deploy (H100, exit 6).
    alert_channel_check || exit $?
    # **Only now is it deployed.** Written last and atomically, so a run that stops anywhere above
    # leaves the old record and the next tick tries again.
    printf '%s\n' "$after" > "$STATE.tmp" && mv "$STATE.tmp" "$STATE"
    history_append "$after" "$schema_after" deploy
    say "recorded $after in $STATE and $HISTORY"
    exit 0
fi
say "FAILED to come up at $after after $(( $(date +%s) - t0 ))s"
say "the one-shots are where a bootstrap failure lives and they have already exited — read"
say "them explicitly, they do not appear in a plain \`ps\` (H65):"
say "    docker compose ps -a"
say "    docker compose logs migrate airflow-init"

# **A bad deploy: hold first, then go back if going back can work (owner 「A」, 2026-11-16).**
# Before this, the next tick saw HEAD ahead of `.deployed-sha` and retried the same commit every
# five minutes, recreating the whole stack each time, with nobody told.
hold_because "the deploy of $after failed"
why="up --wait or /health failed"
# **Across a migration there is no way back, so none is tried.** The api's startup guard demands the
# exact revision it ships against, and the older code exited 3 against a newer schema when this was
# measured on a dev stack. An unreadable revision counts as moved: «the same» has to be shown.
if [ "$schema_before" = "$UNREAD" ] || [ "$schema_after" = "$UNREAD" ] || [ "$schema_before" != "$schema_after" ]; then
    send_alert "the deploy of $(short "$after") failed ($why) after migration $schema_before -> $schema_after. NOT rolled back: the older code refuses the newer schema. Site down. Timer held. Fix forward: publish a fix, then remove $HOLD."
    exit 13
fi
# **No pull on the way back (Q4):** the box's disk is the constraint, and a pull during an outage
# that fills it is a second failure. Whatever prunes images must keep `.deployed-sha`'s.
if ! images_on_disk "$deployed"; then
    send_alert "the deploy of $(short "$after") failed ($why). NOT rolled back: the images for $(short "$deployed") are not on disk, and nothing was pulled. Timer held."
    exit 13
fi
if return_to "$deployed"; then
    history_append "$deployed" "$schema_after" rollback
    send_alert "the deploy of $(short "$after") failed ($why). Rolled back to $(short "$deployed"), schema $schema_after unchanged, serving again. Timer held: remove $HOLD after the fix."
    exit 12
fi
send_alert "the deploy of $(short "$after") failed ($why), and the return to $(short "$deployed") failed too. NOT serving. Timer held."
exit 13
