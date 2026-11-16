# `deploy/` — how the box updates itself

**«CD pulls; nothing reaches into this VM.» Until 2026-09-04 that was a stance with no
mechanism** — no deploy script existed anywhere in the tree and nothing ran `git pull`. This is the
mechanism, and it is deliberately the smallest thing that can be correct.

## What it is

`pull-deploy.sh` — a `git pull --ff-only`, and **only if the commit differs from the one recorded in
`.deployed-sha`**: pull the images GitHub Actions built for that full sha, migrate, then
`up -d --wait --wait-timeout 900` and ask `/health` through the proxy. When any of those fails, it
holds the timer (`.deploy-hold`), goes back to the last good version when that is safe, and sends
one alert that says how it ended (below).
`upto-pull-deploy.service` / `.timer` — systemd, every 5 minutes, as the login user, not root.

## Install, once, on the box

```sh
git clone https://github.com/JacksonG-TW/Uptoyou.git ~/upto   # the public repository
cd ~/upto && cp .env.example .env && $EDITOR .env             # secrets never enter the repo
sudo cp deploy/upto-pull-deploy.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now upto-pull-deploy.timer
```

In `.env`, set `UPTO_IMAGE_PREFIX=ghcr.io/jacksong-tw/upto-` so the box pulls images instead of
building them, and `UPTO_BIND=0.0.0.0` so the proxy answers beyond loopback. Bring the stack up once
by hand, then record what is serving with `deploy/pull-deploy.sh --record`. It checks that the
api, the proxy and the scheduler run this clone's commit and that `/health` answers, then writes
`.deployed-sha` and the first line of `.deployed-history`. The timer refuses to run until
`.deployed-sha` exists.

Edit `WorkingDirectory` and `ExecStart` in the unit if the clone is not at `/home/ec2-user/upto`.
Nothing else in either file hardcodes a path.

The box needs Docker Compose with `up --wait-timeout` and `up --pull`. The script asks
`docker compose up --help` first and refuses to start without them (exit 15).

## Done — what a person can see

**Push a commit here; once Actions has built its images, the next timer tick serves it, with nobody
logging in** — unless it changes `deploy/` (other than its `.md` files), `compose.yaml` or `airflow/init.sh`, which a person runs
by hand.

```sh
systemctl status upto-pull-deploy.timer      # next elapse
journalctl -u upto-pull-deploy -n 40         # what the last tick did
cat ~/upto/.deployed-history                 # one line per deploy and rollback
curl -s localhost/health                     # {"status":"ok","database":"reachable","instance":"…","stream_listener":"up"}
```

A tick that found nothing prints two lines and exits 0. A tick that deployed prints the commit
range it moved through and how many seconds `up` took, then checks the alert channel and prints
`alert channel: telegram_alerts present`.

**`.deployed-history`** gets one line each time the box changes what it serves: the UTC time, the
full sha, the schema revision, and how (`deploy`, `rollback`, `hand-rollback`, or `hand` for
`--record`). Only `pull-deploy.sh` writes it, and it only appends.

## When a deploy goes wrong

A deploy is bad when the migration fails, when `up --wait` fails or has not finished after 900
seconds, or when `/health` through the proxy is not ok right after. Every bad deploy first writes
the reason into `.deploy-hold`, in the clone (`~/upto/.deploy-hold` on the box). The timer keeps
firing, but each tick sees the file and does nothing, so the bad deploy is not retried. When it has
finished, it sends one alert that says how it ended: still serving the old version (a failed
migration), rolled back, not rolled back, or not serving.
What it does in between depends on the database:

| What went wrong | What the script does | Exit |
|---|---|---|
| The migration failed | Nothing else. The migration runs in one transaction, so the database undoes it, and the old version never stopped serving. The script reads the revision again: if it reads otherwise, the alert says so, and the migrate log is the first thing to read. | 11 |
| `up` or `/health` failed, the schema did not move | Returns to the sha in `.deployed-sha` with `--pull never`, checks `/health`, appends a `rollback` line. | 12 |
| `up` or `/health` failed, the migration moved the schema | No rollback: the older code refuses a newer schema. The fix goes forward. | 13 |
| `up` or `/health` failed, the last good images are not on disk | No rollback: it never pulls on the way back. | 13 |
| The way back failed too | The alert says the site is not serving. | 13 |

**The alert** goes out through the scheduler's existing `telegram_alerts` Connection, from inside
that container. `pull-deploy.sh` never reads the bot token, and prints only whether the message
was sent. An alert that cannot be sent is logged and never changes the outcome.

**To go back by hand**, run `deploy/pull-deploy.sh --rollback`, or `--rollback <full sha>`. It
returns to the newest sha in `.deployed-history` other than the one in `.deployed-sha`, or to the
given sha. It
refuses, with nothing moved (exit 14), unless:

- the sha is in `.deployed-history`;
- `compose.yaml` and `airflow/init.sh` are the same at that sha as now;
- its schema revision equals the database's;
- its images are already on disk.

It may name the sha in `.deployed-sha` itself, which is how a person brings that version back after
an exit 13. It holds the timer first, and it alerts when done.

**After any of these, remove `.deploy-hold` to resume.** The next tick deploys the newest commit
again, so remove it once a fix is on `main`, or when going forward again is what you want. A person
can also hold the box by hand at any time with `touch ~/upto/.deploy-hold`.

**Exit codes:** 0 nothing to do or deployed · 2 an argument it does not know · 3 no `flock` · 4 `git pull --ff-only` failed (diverged
or unreachable) · 5 `deploy/` (other than its `.md` files), `compose.yaml` or `airflow/init.sh` changed in the pull — the refusal prints the new file's steps to run by hand with the tag set (a plain `--once` would find no change) · **6 the stack is UP but
`telegram_alerts` is absent** — the failure alerts send nothing until both `UPTO_TELEGRAM_BOT_TOKEN` and
`UPTO_TELEGRAM_CHAT_ID` are set in `.env` and `airflow-init` is recreated; re-check with
`deploy/pull-deploy.sh --check-alert-channel` (the box was silent for the whole launch
because an empty chat id is legal everywhere else). The check asks for the Connection by id through
a hook and never prints a value. · 7 `.deployed-sha` is missing · 8 no image is tagged with this
commit (is `UPTO_IMAGE_PREFIX` set?) · 9 the images are still missing an hour after the commit was
first seen · 10 `.deployed-sha` names a commit this clone does not have · 11 the migration failed;
held, the old version still serving · 12 a bad deploy, rolled back, held · 13 a bad deploy, not
rolled back, held · 14 `--rollback` or `--record` refused, nothing moved · 15 Compose lacks
`--wait-timeout` or `--pull`, nothing moved.

## The three things it gets right, and the one somebody will "fix"

**Code is never bind-mounted**, so a pull changes nothing until the matching images are pulled *and*
the containers recreated. A stale image does not announce itself. Hence pull, then `up -d --wait`.

**A pull that changed nothing does nothing.** Rebuilding on a timer when HEAD has not moved is how
a box restarts itself in the middle of somebody's round for no reason.

**`--ff-only`.** A clone that has diverged stops rather than merging. A merge commit made by a
timer at 04:00 is a state nobody can reason about the next morning.

**The one to read before changing:** the box never builds; it pulls images by full sha. **The `test`
profile must never reach the `up`**: `tests` is the one container holding the database owner's
credential at rest.

## What this is not

It is not a rollback across a migration. No path ever runs a down-migration: migrations only go
forward, so a deploy that moved the schema is fixed by pushing a good commit and waiting for its
images and the next tick. It is not blue-green either. One box has room for one stack, so a bad
deploy is offline from the moment `up` replaces it until the way back is up again.
