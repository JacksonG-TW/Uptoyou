# `deploy/` — how the box updates itself

**«CD pulls; nothing reaches into this VM.» Until 2026-09-04 that was a stance with no
mechanism** — no deploy script existed anywhere in the tree and nothing ran `git pull`. This is the
mechanism, and it is deliberately the smallest thing that can be correct.

## What it is

`pull-deploy.sh` — a `git pull --ff-only`, and **only if the commit differs from the one recorded in
`.deployed-sha`**: pull the images GitHub Actions built for that full sha, migrate, then `up -d --wait`.
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
by hand, then record what is serving with `git rev-parse HEAD > .deployed-sha`; the timer refuses to
run until that file exists.

Edit `WorkingDirectory` and `ExecStart` in the unit if the clone is not at `/home/ec2-user/upto`.
Nothing else in either file hardcodes a path.

## Done — what a person can see

**Push a commit here; once Actions has built its images, the next timer tick serves it, with nobody
logging in** — unless it changes `deploy/`, `compose.yaml` or `airflow/init.sh`, which a person runs
by hand.

```sh
systemctl status upto-pull-deploy.timer      # next elapse
journalctl -u upto-pull-deploy -n 40         # what the last tick did
curl -s localhost/health                     # {"status":"ok","database":"reachable","instance":"…","stream_listener":"up"}
```

A tick that found nothing prints two lines and exits 0. A tick that deployed prints the commit
range it moved through, then checks the alert channel and prints `alert channel: telegram_alerts
present`.

**Exit codes:** 0 nothing to do or deployed · 3 no `flock` · 4 `git pull --ff-only` failed (diverged
or unreachable) · 5 `deploy/`, `compose.yaml` or `airflow/init.sh` changed in the pull — the refusal prints the new file's steps to run by hand with the tag set (a plain `--once` would find no change) · **6 the stack is UP but
`telegram_alerts` is absent** — the failure alerts send nothing until both `UPTO_TELEGRAM_BOT_TOKEN` and
`UPTO_TELEGRAM_CHAT_ID` are set in `.env` and `airflow-init` is recreated; re-check with
`deploy/pull-deploy.sh --check-alert-channel` (the box was silent for the whole launch
because an empty chat id is legal everywhere else). The check asks for the Connection by id through
a hook and never prints a value. · 7 `.deployed-sha` is missing · 8 no image is tagged with this
commit (is `UPTO_IMAGE_PREFIX` set?) · 9 the images are still missing an hour after the commit was
first seen · 10 `.deployed-sha` names a commit this clone does not have.

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

It is not a rollback. A bad commit is fixed by pushing a good one and waiting for its images and the next tick (to hold the
box meanwhile, `touch .deploy-hold`) — which
is the plain shape for one box and one person, and worth saying out loud rather than discovering.
