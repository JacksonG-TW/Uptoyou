#!/bin/sh
# Bootstrap — migrations and the township seed — runs in the **migrate** service, once, before
# anything serves. Every other container sharing this image skips straight to its command.
#
# **The product's criterion is that the compose file brings the stack up, and that still holds.**
# The work did not move to a human; it moved to a one-shot service, which the deploy runs once
# (`docker compose run --rm migrate`) before `up`.
#
# **Why it moved at all (A15 / D115).** These two steps need the database **owner**: `alembic`
# does DDL and the seed writes a reference table. Since A15 the api container connects as
# `upto_api`, which can do neither — and putting the owner's credential back into the container
# that serves requests is exactly the boundary the ruling exists to draw. So the credential lives
# in `migrate` (and in `tests`), and the process that answers a request cannot migrate, seed, or
# `TRUNCATE` anything.
#
# `alembic upgrade head` is idempotent: on an already-current database it prints nothing and exits
# 0. If it fails, the container fails, which is the point — an API serving against a schema it does
# not expect is worse than an API that did not start. With this split, that failure now happens in
# `migrate` and stops the deploy before `up`, which is the same guarantee one step earlier.
set -e

if [ "${UPTO_BOOTSTRAP:-}" = "1" ]; then
    # The four login roles first: revision 0032 grants to them and cannot create them, because a
    # migration cannot hold a password. See `upto/roles.py` for why this is not in airflow/init.sh.
    echo "entrypoint: ensuring the service roles (D115)"
    python -m upto.roles
    echo "entrypoint: applying migrations"
    alembic upgrade head
    echo "entrypoint: seeding the township-station map"
    # Ticket 06's one command, and it is idempotent: an upsert keyed on the township code, with
    # a self-check that refuses rather than writing a mapping that disagrees with the ingested
    # observations. Running it on every start is what makes `docker compose up` sufficient.
    python -m upto.seed.township_station
    echo "entrypoint: bootstrap complete"
fi

exec "$@"
