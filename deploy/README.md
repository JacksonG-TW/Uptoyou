# `deploy/` — how the box updates itself

**D59: «CD pulls; nothing reaches into this VM.» Until 2026-09-04 that was a stance with no
mechanism** — no deploy script existed anywhere in the tree and nothing ran `git pull`. This is the
mechanism, and it is deliberately the smallest thing that can be correct.

## What it is

`pull-deploy.sh` — pull, and **only if HEAD moved**: build, then `up -d --wait`.
`upto-pull-deploy.service` / `.timer` — systemd, every 5 minutes, as the login user, not root.

## Install, once, on the box

```sh
git clone https://github.com/Jackson0612/Uptoyou.git ~/upto   # the PUBLIC extract: app/ only (D47)
cd ~/upto && cp .env.example .env && $EDITOR .env             # H16: secrets never enter the repo
sudo cp deploy/upto-pull-deploy.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now upto-pull-deploy.timer
```

Edit `WorkingDirectory` and `ExecStart` in the unit if the clone is not at `/home/ec2-user/upto`.
Nothing else in either file hardcodes a path.

## Done — what a person can see

**Push a commit here; within five minutes the box serves it, with nobody logging in.**

```sh
systemctl status upto-pull-deploy.timer      # next elapse
journalctl -u upto-pull-deploy -n 40         # what the last tick did
curl -s localhost/health                     # {"status":"ok","database":"reachable"}
```

A tick that found nothing prints one line and exits 0. A tick that deployed prints the commit
range it moved through.

## The three things it gets right, and the one somebody will "fix"

**H28** — nothing is bind-mounted, so a pull changes nothing until the images are rebuilt *and* the
containers recreated. A stale image does not announce itself. Hence build, then `up -d --wait`.

**A pull that changed nothing does nothing.** Rebuilding on a timer when HEAD has not moved is how
a box restarts itself in the middle of somebody's round for no reason.

**`--ff-only`.** A clone that has diverged stops rather than merging. A merge commit made by a
timer at 04:00 is a state nobody can reason about the next morning.

**The one to read before changing:** the operations manual says always `docker compose --profile
test build` (H64), because a plain build silently skips the profile-gated `tests` image and a round
then measures last week's runner. **That rule is about running rounds, and this box never runs
one.** A plain build covers exactly the services this box starts, and skipping `tests` saves an
image nobody will run on a 2 GB instance. **The profile must never reach the `up` either way**:
`tests` is the one container holding the database owner's credential at rest (A15/D115).

## What this is not

It is not a rollback. A bad commit is fixed by pushing a good one and waiting five minutes — which
is the honest shape for one box and one person, and worth saying out loud rather than discovering.
