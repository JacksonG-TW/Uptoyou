"""A9 — every ingest DAG asks whether the publication it just stored is *shaped* like the last one.

*Owner-ruled 2026-08-19: all five sources now, not the one with history.*

**The question.** D102 gave every publication the ordered field names of the file it came from and a
hash of that list, and M3 proved the columns fill. Nothing yet **reads** them. A source can rename a
column, drop one, or serve a truncated file, and this pipeline stores the result and carries on: the
ingest fetched, hashed and parsed exactly as designed, so it is green, and the ledger's `stored`
is true. The damage shows up days later as names that stopped resolving.

So one task per ingest DAG, between the ingest and whatever depends on it, asking two questions of
the publication the ledger says was just stored:

1. **Is the shape the same as the previous publication's?** `column_signature` against
   `column_signature`, and when they differ the answer names the columns that appeared and vanished
   from `column_names` — a hash alone says "something moved" and nothing anybody can act on.
2. **Did the row count collapse?** A drop of 20% or more against the previous publication.

**Why 20%, and what it is not.** It is a *collapse* detector, not a drift detector: a truncated
download, a publisher's partial extract, a filter left on upstream. Real month-to-month movement in
these registries has never been observed near it — 食藥署 47,741 rows, 營業稅籍 14.5k of 1.7M — but
that is one publication for four of the five sources, so the threshold is **a starting line chosen
to be obviously safe, to be moved once the DAGs have accumulated history**, not a measured one.
Saying so is the point: a threshold presented as measured when it was guessed is worse than a guess.

**A growth in rows is never a failure.** A source that doubles is a source that published more, and
the shape check is what would catch a doubling that came from a changed file format.

**«n/a» is a skip, and that is the whole design of this file.** Four of the five sources have exactly
one publication today (place · brand · storefront · business_status = 1; business_tax = 5), so the
comparison is *impossible* for four of them, and a check that cannot compare must not be green.
Green is a pass, a pass is a claim, and H37 is the standing record of what a claim nobody measured
costs here. Airflow's third state means "a precondition was not met, so this did not run", which is
exactly true. **So downstream tasks that must survive an n/a carry
`trigger_rule=TriggerRule.NONE_FAILED`** — see `place_reference_ingest.py`, where the asset emitter
does: on the very first publication the check *cannot* compare, and the classify backfill must still
be told the publication landed.

**The three states map to Airflow's three, and nothing is overloaded:**

    pass  → green, one line saying what was compared
    n/a   → skipped, one line naming the precondition that was missing
    fail  → red, one sentence — the drift or the collapse, with the numbers

**Read `db_source` and nothing else for the key.** The DAG files carry a display label per source
(`foodtracer-brands`, `gcis-status`) that is **not** what the ledger and the publication tables
store (`taipei-foodtracer`, `gcis-restaurant-registry`). Keying this check off the display label
would find zero rows for three of four sources, and zero rows reads as *no previous publication*,
which is a false n/a — the exact shape of the bug the n/a state exists to prevent. The mismatch is
recorded here rather than fixed, because renaming a label that appears in a year of logs is a
separate decision.

**Imported by a sibling path insert, not by Airflow's own path.** Airflow 3.0.2 does not put the
bundle folder on `sys.path` — Airflow 2 did — so each DAG file that imports this one inserts the
folder itself, with the measurement in a comment beside the line.

Tested by `app/api/tests/test_publication_check.py` — `verdict()` is pure, takes two dicts, and
needs no Airflow, no network and no database.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # the runtime import stays inside the task (below): the provider is heavy and
    # exists only in the Airflow image, while this module is imported by the host-side test too.
    from airflow.providers.postgres.hooks.postgres import PostgresHook

# **Airflow is imported inside `make_check_task`, not here, and that is what makes this file
# testable.** The host has no Airflow — the DAGs run in the airflow images' own interpreter — so a
# module-level `import airflow` would put the pure comparison behind a dependency the test runner
# does not have, and the test would have to be a copy of the logic instead of the logic. The DAG
# files call `make_check_task` at parse time, so inside Airflow the import happens exactly as
# early as it ever did.

# A15 / D115: the pipeline runs as `upto_ingest`, which can read nothing that names a
# person (§3.0, D14). `upto_postgres` is the owner's connection and no DAG uses it.
POSTGRES_CONNECTION = "upto_ingest_postgres"

# A drop of this share or more against the previous publication fails the check. See the docstring:
# chosen to be obviously safe, to be moved once there is history to move it from.
COLLAPSE_SHARE = 0.20

PASS = "pass"
NOT_APPLICABLE = "n/a"
FAIL = "fail"

# source key in the ledger and the publication table  →  (table, row-count column, ledger FK column)
#
# The row-count columns do not share a name, and that is not an accident worth papering over: each
# publication counts the thing its own source publishes. All five are nullable, so `None` here means
# *this publication did not record a count*, never zero.
SOURCES = {
    "fda-97": ("place_publication", "place_rows", "place_publication_id"),
    "taipei-foodtracer": ("brand_publication", "pair_rows", "brand_publication_id"),
    "taipei-hygiene-grade": ("storefront_publication", "name_rows", "storefront_publication_id"),
    "gcis-restaurant-registry": (
        "business_status_publication", "status_rows", "business_status_publication_id"),
    "fia-business-tax": ("business_tax_publication", "tax_rows", "business_tax_publication_id"),
}


def _column_drift(current: dict, previous: dict) -> tuple[str | None, str]:
    """The shape half. Returns (failure sentence or None, what-was-done line)."""
    here, there = current.get("signature"), previous.get("signature")
    if here is None or there is None:
        which = "this publication" if here is None else "the previous publication"
        return None, (
            "shape NOT compared — {} carries no `column_signature` (it predates revision 0021, "
            "and D102 backfills nothing)".format(which))
    if here == there:
        return None, "shape unchanged ({}…)".format(here[:12])

    # Differ. Name the columns, because "the hash moved" is an answer nobody can act on.
    mine = current.get("names") or []
    theirs = previous.get("names") or []
    appeared = [name for name in mine if name not in theirs]
    vanished = [name for name in theirs if name not in mine]
    if not appeared and not vanished:
        # Same set, different order — the signature is over the *ordered* list by D102, so a
        # reordering is a real change of shape and this is what it looks like.
        detail = "the same {} columns in a different order".format(len(mine))
    else:
        detail = "appeared {} · vanished {}".format(appeared or "nothing", vanished or "nothing")
    return (
        "the source changed the shape of its file: {} ({}… was {}…)".format(
            detail, here[:12], there[:12]),
        "shape CHANGED",
    )


def _row_collapse(current: dict, previous: dict) -> tuple[str | None, str]:
    """The row-count half. Returns (failure sentence or None, what-was-done line)."""
    here, there = current.get("rows"), previous.get("rows")
    if here is None or there is None:
        which = "this publication" if here is None else "the previous publication"
        return None, "row count NOT compared — {} recorded none".format(which)
    if there == 0:
        # No share of zero exists. A previous publication of zero rows is itself odd, so say it
        # rather than dividing by it.
        return None, "row count NOT compared — the previous publication recorded 0 rows"
    if here >= there:
        return None, "row count {} against {}, not down".format(here, there)
    share = (there - here) / there
    if share >= COLLAPSE_SHARE:
        return (
            "the row count collapsed: {} rows against the previous publication's {}, down "
            "{:.1%} — at or past the {:.0%} line".format(here, there, share, COLLAPSE_SHARE),
            "row count DOWN {:.1%}".format(share),
        )
    return None, "row count {} against {}, down {:.1%} — inside the line".format(here, there, share)


def verdict(source: str, current: dict | None, previous: dict | None) -> tuple[str, str]:
    """Compare two publications. Pure — no Airflow, no database. Returns (state, sentence).

    `current` and `previous` are dicts with `id`, `signature`, `names`, `rows`. `previous` is None
    when this source has never published before; `current` None means the ledger said `stored` and
    named no publication, which is a bug rather than a quiet day.
    """
    if current is None:
        return FAIL, (
            "{}: the ledger's latest run says `stored` and names no publication row, so there is "
            "nothing to check the shape of — a missing provenance link is a bug, not a quiet "
            "day".format(source))
    if previous is None:
        return NOT_APPLICABLE, (
            "{}: no previous publication for `{}`; the comparison is not possible and was not "
            "made. Publication id {} is the first this source has stored, so this check re-runs "
            "against a real predecessor the next time the source republishes.".format(
                source, source, current.get("id")))

    shape_failure, shape_line = _column_drift(current, previous)
    rows_failure, rows_line = _row_collapse(current, previous)
    compared = "publication {} against {}: {}; {}".format(
        current.get("id"), previous.get("id"), shape_line, rows_line)

    if shape_failure or rows_failure:
        both = " AND ".join(part for part in (shape_failure, rows_failure) if part)
        return FAIL, "{}: {} — {}".format(source, both, compared)

    if "NOT compared" in shape_line and "NOT compared" in rows_line:
        # Both halves were unanswerable. There is a previous publication, so this is not the
        # first-publication n/a, but nothing was measured either — and a green task here would be
        # the false pass the whole file exists to refuse.
        return NOT_APPLICABLE, (
            "{}: a previous publication exists but neither question could be answered — {}".format(
                source, compared))

    return PASS, "{}: {}".format(source, compared)


def _read(hook: PostgresHook, table: str, rows_column: str, publication_id: int) -> dict | None:
    records = hook.get_records(
        "select id, column_signature, column_names, {} from {} where id = %s".format(
            rows_column, table),
        parameters=(publication_id,),
    )
    if not records:
        return None
    identifier, signature, names, rows = records[0]
    return {"id": identifier, "signature": signature, "names": names, "rows": rows}


def _read_previous(
    hook: PostgresHook, table: str, rows_column: str, source: str, current_id: int
) -> dict | None:
    """The publication stored before `current_id`, by id.

    **By id and not by `detected_at`.** The sequence is monotonic per table and `max_active_runs=1`
    on every one of these DAGs means two runs cannot interleave, so a lower id is an earlier
    publication. `detected_at` would answer the same question today and would also tie, because two
    publications detected in the same second sort arbitrarily.
    """
    records = hook.get_records(
        "select id, column_signature, column_names, {} from {} "
        " where source = %s and id < %s order by id desc limit 1".format(rows_column, table),
        parameters=(source, current_id),
    )
    if not records:
        return None
    identifier, signature, names, rows = records[0]
    return {"id": identifier, "signature": signature, "names": names, "rows": rows}


def make_check_task(db_source: str, task_id: str = "check_publication"):
    """Build the check task for one source. Call inside a `@dag` body.

    The returned task takes the ingest's verdict string as its only argument — **used for nothing
    but the dependency edge**, so this task sits downstream of the ingest and the graph says so.
    Every decision here is a `select`; reading prose for a decision is H36's shape.
    """
    if db_source not in SOURCES:
        raise KeyError(
            "{} is not a publication source this check knows — the key is what the ledger and the "
            "publication table store, never the DAG's display label".format(db_source))
    table, rows_column, foreign_key = SOURCES[db_source]

    from airflow.exceptions import AirflowSkipException
    from airflow.providers.postgres.hooks.postgres import PostgresHook
    from airflow.sdk import task

    # No `trigger_rule`: `all_success` is the default and it is what is wanted — the check has
    # nothing to say about a publication whose ingest failed.
    @task(task_id=task_id)
    def check_publication(verdict_text: str) -> str:
        hook = PostgresHook(postgres_conn_id=POSTGRES_CONNECTION)
        latest = hook.get_records(
            "select outcome, {} from ingest_run where source = %s "
            " order by started_at desc limit 1".format(foreign_key),
            parameters=(db_source,),
        )
        if not latest:
            raise RuntimeError(
                "{}: the ingest succeeded and wrote no ledger row, so there is no publication to "
                "check — a missing row is a bug rather than a quiet day".format(db_source))
        outcome, publication_id = latest[0]
        if outcome != "stored":
            # Nothing new was stored, so there is no new shape and no new count. Skipped rather
            # than green for the same reason as every other n/a here: nothing was compared.
            raise AirflowSkipException(
                "{}: the latest run's outcome is `{}`, so no publication landed and there is "
                "nothing to compare. The ingest above succeeded — this is the designed quiet "
                "day.".format(db_source, outcome))

        current = _read(hook, table, rows_column, publication_id) if publication_id else None
        previous = (
            _read_previous(hook, table, rows_column, db_source, publication_id)
            if publication_id else None)

        state, sentence = verdict(db_source, current, previous)
        if state == FAIL:
            raise RuntimeError(sentence)
        if state == NOT_APPLICABLE:
            raise AirflowSkipException(sentence)
        print(sentence)
        return verdict_text

    return check_publication
