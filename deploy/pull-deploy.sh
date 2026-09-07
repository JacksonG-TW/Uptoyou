#!/bin/sh
# Pull, rebuild what changed, bring the stack up. The whole of D59's "CD pulls" on the box.
#
#     app/deploy/pull-deploy.sh            # what the timer runs
#     app/deploy/pull-deploy.sh --once     # same thing by hand, same output
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
# **H28 — nothing is bind-mounted, so a pull that changes source changes NOTHING until the images
# are rebuilt AND the containers recreated.** A stale image does not announce itself: every file on
# disk reads correct while the container serves last week's code. So this builds before it ups, and
# ups with `--wait` so a container that will not come up is a failure here rather than a surprise
# later.
#
# **H64 in reverse, and this is the line somebody will "fix" — read before changing it.** The
# operations manual says always `docker compose --profile test build`, because a plain build
# silently skips the profile-gated `tests` image and a round then measures last week's runner.
# **That rule is about running rounds. This box never runs one.** A plain `docker compose build`
# builds every service that is not profile-gated — which is exactly the set this box runs — and
# skipping `tests` here saves an image nobody will start on a 2 GB instance. **The profile must
# also never appear on the `up`**: `tests` is the one container holding the database owner's
# credential at rest (A15/D115), and starting it is what `split_boot_check.sh` asserts against.
#
# **A pull that changed nothing must do nothing.** Rebuilding and recreating on a timer when HEAD
# has not moved is how a box restarts itself in the middle of somebody's round for no reason.
# ---------------------------------------------------------------------------------------------

set -eu

HERE=$(cd "$(dirname "$0")" && pwd)      # <clone>/deploy
APP=$(cd "$HERE/.." && pwd)              # <clone>  — `app/`'s contents ARE the repo root here
LOCK=${DEPLOY_LOCK:-/tmp/upto-pull-deploy.lock}
say() { echo "$(date -u +%FT%TZ) pull-deploy: $*"; }

# **One at a time.** A build on a small instance can outlast the timer's period; two overlapping
# runs would fight over the image tags and the containers. `flock` is in util-linux and is on the
# AMI; if it is ever absent this exits rather than running unguarded.
if command -v flock >/dev/null 2>&1; then
    exec 9>"$LOCK"
    flock -n 9 || { say "another run holds $LOCK — skipping this tick"; exit 0; }
else
    say "flock not found; refusing to run unguarded"; exit 3
fi

cd "$APP"

before=$(git rev-parse HEAD)
say "at $before, fetching"
# **`--ff-only`.** A clone that has diverged — somebody edited a file on the box — must STOP, not
# merge. A merge commit created by a timer at 04:00 is a state nobody can reason about afterwards.
if ! git pull --ff-only --quiet; then
    # **Single quotes, and this line has already bitten.** In double quotes the backticks around
    # the command name were COMMAND SUBSTITUTION: the failure message re-ran `git pull --ff-only`,
    # which is why the hint block printed twice the first time this path was exercised. Harmless
    # for a pull; not harmless as a habit in a script that also builds and restarts things.
    say 'REFUSED: git pull --ff-only failed. The clone has diverged or the remote is unreachable.' 
    say "         Nothing was built and nothing was restarted. Look before forcing anything."
    exit 4
fi
after=$(git rev-parse HEAD)

# **A box that is AHEAD of its remote is running code that is in no repository — say so.**
# Found while testing this script: `--ff-only` only refuses when the remote has ALSO moved. A
# local commit made on the box (an edit, a "quick fix") leaves HEAD ahead, the pull succeeds
# trivially, and every tick afterwards prints "no change" while the box serves something nobody
# can look up. That is H28's family — the served thing is not the named thing — and the only
# difference here is that the artefact reading correct is `git log` on somebody else's machine.
upstream=$(git rev-parse --abbrev-ref '@{u}' 2>/dev/null || echo "")
if [ -n "$upstream" ] && ! git merge-base --is-ancestor "$after" "$upstream"; then
    say "WARNING: HEAD is AHEAD of $upstream — this box holds commit(s) that are in no repository:"
    git --no-pager log --oneline "$upstream..$after" | sed 's/^/    /'
    say "         Deploying anyway (the box keeps serving), but what runs here cannot be looked"
    say "         up from the repository until these are pushed or dropped."
fi

if [ "$before" = "$after" ]; then
    say "no change at $after — nothing to do"
    exit 0
fi

say "moved $before -> $after"
git --no-pager log --oneline "$before..$after" | sed 's/^/    /'

# **This box does not build, and that is the point** (owner 「公開」 2026-09-07; the research is in
# the private repository, `idea & img/ghcr-research.md`). It built its own images until then, and on
# 2026-09-05 that wedged it for twelve hours — `npm ci` and a Vite build on a swapless 2 GB instance
# with the stack running (H76's neighbour). The images are built on the development machine and
# pushed to GHCR as PUBLIC packages, so this pull needs **no credential**: «You can also access
# public container images anonymously» (GitHub, read 2026-09-07). What arrives is named by the
# extract's own commit, so «what is this running» is answerable from a repository anybody can fetch.
#
# **A pull is I/O, not memory**, so the failure this replaces is gone rather than mitigated, and the
# stack keeps serving until the recreate — the outage window is a container restart instead of a
# frontend build. `.env` carries `UPTO_IMAGE_PREFIX=ghcr.io/jacksong-tw/upto-`; the tag is derived
# below from the commit this clone just moved to. **A rollback is therefore a `git` operation
# rather than an `.env` edit**: check the clone out at an earlier extract commit and run this, and
# the images follow the code by construction.
# **The tag IS the commit this clone just moved to, and that dissolves a trade** (ruled
# 2026-09-07). The alternative shapes were: follow `:latest` and inherit H28 one layer up — a tag
# that resolves to something different each day is the stale image that does not announce itself —
# or pin a sha by hand in `.env`, which is a person editing a file on every deploy. This clone IS
# the public extract, so the commit it is standing on is exactly what `publish_images.sh` tagged
# with. No edit, no moving tag, and **a missing image for this sha fails the pull loudly**, which is
# the failure we want: the box refuses to start something nobody published rather than quietly
# serving whatever `:latest` last pointed at. `:latest` still exists in the registry as a human
# convenience; nothing here reads it.
UPTO_IMAGE_TAG="$after"
export UPTO_IMAGE_TAG
say "pulling images at $after"
docker compose pull --quiet

# **`--wait` is the difference between deploying and hoping.** Without it `up -d` returns as soon
# as the containers are created, and a container that dies on its healthcheck is discovered by a
# member instead of by this script. The `migrate` one-shot runs here too and `api` waits on its
# success (A15/D115), so a failed migration stops the deploy one container earlier.
say "starting"
if docker compose up -d --wait; then
    say "UP at $after"
else
    status=$?
    say "FAILED to come up at $after (exit $status)"
    say "the one-shots are where a bootstrap failure lives and they have already exited — read"
    say "them explicitly, they do not appear in a plain \`ps\` (H65):"
    say "    docker compose ps -a"
    say "    docker compose logs migrate airflow-init"
    exit "$status"
fi
