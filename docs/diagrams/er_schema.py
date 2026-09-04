#!/usr/bin/env python3
"""Turn a `pg_dump --schema-only` file into the DDL an ERD generator can read.

**Why this script exists at all.** This project has no SQLAlchemy declarative models —
the schema lives in 19 hand-written Alembic migrations that call `op.create_table`, and
queries are written as SQL through SQLAlchemy Core. An ERD tool that parses model classes
therefore finds nothing here. What it can read is SQL DDL, so the *live database* is the
source of truth for the diagram: `pg_dump --schema-only` out of the running container,
reduced to what an ERD is made of.

**Why not the migrations.** `alembic upgrade head --sql` also emits DDL without a
database, but it emits the whole *history*: 40 `ALTER TABLE` statements, several of them
`DROP CONSTRAINT`, replaying every intermediate shape. A parser reading that file sees
each table as it was first created, not as it is. `pg_dump` sees only the end state.

**What is dropped, and why it is safe.** CHECK constraints, indexes, triggers, functions,
sequences, extensions and psql meta-commands (`\\restrict`) are removed. None of them
appear in an entity-relationship diagram, two of them (dollar-quoted plpgsql bodies,
backslash commands) are not SQL and stop the parser dead. What is kept is columns, their
types and nullability, PRIMARY KEY and FOREIGN KEY — and those are *inlined into the
CREATE TABLE*, because pg_dump emits them as separate `ALTER TABLE ... ADD CONSTRAINT`
statements which the parser reads as tables with no keys at all.

**What is projected away.** A faithful diagram of all 26 tables with all their columns is
unreadable — `business_tax_row` alone carries eight industry code/name columns. So each
table is projected down to its keys (always kept, in full) plus the few columns that carry
the story: provenance, hashes, the values a reader is looking for. The allowlist is
`STORY` below; every column in it was read out of the dump, and a name that stops existing
raises rather than being silently skipped.

Usage — from `app/`:

    docker compose exec -T db sh -lc \\
      'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --schema-only --no-owner --no-privileges' \\
      | python3 docs/diagrams/er_schema.py --out docs/diagrams/ddl

Standard library only, and Python 3.9 clean: it runs on this machine's host interpreter,
which is older than the one in the container.
"""

import argparse
import os
import re
import sys

# --- the four clusters, plus the context each one needs to keep its edges -------------
#
# A cluster diagram that hides the parent of a foreign key shows a dangling column, so a
# few tables appear in a neighbour's diagram as context. They are listed separately so the
# README can say which nodes in a picture are visitors.

CLUSTERS = (
    (
        "reference",
        # The five open-data name sources: one publication row per fetched file, one data
        # row per record, joined to each other by 登錄字號 (registry_no) and 統編
        # (business_no) rather than by any foreign key.
        (
            "place_publication",
            "reference_place",
            "brand_publication",
            "brand_registration",
            "storefront_publication",
            "storefront_name",
            "business_status_publication",
            "business_status_row",
            "business_tax_publication",
            "business_tax_row",
            "search_alias",
            "product_material",
        ),
        # reference_place.township_code is a real FK into the weather cluster.
        ("township_station",),
    ),
    (
        "weather",
        ("forecast_publication", "forecast_reading", "observation_publication",
         "observation_reading", "township_station"),
        (),
    ),
    (
        "product",
        ("circle", "principal", "member", "device_secret", "place", "round", "proposal",
         "weight_contribution", "member_roll", "preference", "trip",
         "round_forecast_baseline"),
        # weight_contribution pins each contextual factor to the exact reading it was
        # computed from — a composite FK into the weather cluster.
        ("forecast_reading", "observation_reading"),
    ),
    (
        "ledger",
        ("ingest_run", "example_embedding"),
        # ingest_run's seven nullable publication columns, at most one of them set.
        ("forecast_publication", "observation_publication", "place_publication",
         "brand_publication", "storefront_publication", "business_status_publication",
         "business_tax_publication"),
    ),
)

# --- the story columns, per table ------------------------------------------------------
#
# Keys are added automatically and are never listed here. What is listed is the handful of
# non-key columns worth a reader's attention.

STORY = {
    "alembic_version": (),
    # Reference sources
    "place_publication": ("source", "content_sha256", "archive_stamp", "detected_at",
                          "place_rows"),
    "reference_place": ("name", "address", "business_no"),
    "brand_publication": ("source", "content_sha256", "detected_at", "pair_rows"),
    "brand_registration": (),
    "storefront_publication": ("source", "content_sha256", "detected_at", "name_rows"),
    "storefront_name": ("name", "grade"),
    "business_status_publication": ("source", "content_sha256", "detected_at",
                                    "status_rows"),
    "business_status_row": (),
    "business_tax_publication": ("source", "content_sha256", "file_stamp", "detected_at",
                                 "tax_rows"),
    "business_tax_row": ("tax_name", "address", "industry_code"),
    # Weather
    "forecast_publication": ("dataset_id", "content_sha256", "detected_at"),
    "forecast_reading": ("value",),
    "observation_publication": ("dataset_id", "content_sha256", "detected_at"),
    "observation_reading": ("station_name", "town_code", "value"),
    "township_station": ("township_name", "station_id", "resolution", "distance_km"),
    # Product
    "circle": ("name", "created_at"),
    "principal": ("created_at",),
    "member": ("nickname", "joined_at"),
    "device_secret": ("secret_sha256", "created_at"),
    "place": ("origin", "name", "registry_no", "category", "category_model",
              "category_input"),
    "round": ("target_hour", "status", "die1", "die2", "closed_at"),
    "proposal": ("weight", "proposed_at"),
    "weight_contribution": ("channel", "contributor", "effect", "reason_visibility"),
    # Who actually rolled, and when. It carries no payload of its own — the story is the
    # three keys and the timestamp — so the columns listed are what a reader needs and no more.
    "member_roll": ("rolled_at",),
    # A1's private surface. `stance` and `persist` are the two that change what the row MEANS
    # (D103's avoid/allow, D17's default-false), so they are drawn and the timestamps are not.
    "preference": ("kind", "value", "stance", "persist", "expires_on"),
    # D114's fourth weight source. It carries no place_id and must not gain one (D28) — the kind
    # of absence a drawn table makes visible.
    "trip": ("signed_at",),
    # D71's stored comparison: no row means no comparison happened, which is not the same as a
    # comparison that found nothing.
    "round_forecast_baseline": ("element", "measure", "slot_start"),
    # D113's authored aliases — `basis` is a column so a withdrawable pairing can be told from an
    # owner-ruled row without reading prose.
    "search_alias": ("alias", "registered_name", "authored_by", "basis"),
    # D77's third table: what a product is made of, as the brand ingest publishes it.
    "product_material": ("brand_name", "product_name", "material_name"),
    # Ledger and the retrieval crib
    "ingest_run": ("source", "started_at", "outcome", "rows_written", "invoked_by"),
    "example_embedding": ("name", "label", "labeled_by", "layer", "embed_model",
                          "source", "source_digest", "embedding"),
}

TITLES = {
    "overview": "Up to you — schema overview (keys only)",
    "reference": "Up to you — reference cluster: five open-data name sources",
    "weather": "Up to you — weather cluster: CWA forecast and observation",
    "product": "Up to you — product cluster: circle, round, roll, audit trail",
    "ledger": "Up to you — ledger cluster: ingest runs and the retrieval crib",
}

CREATE = re.compile(r"^CREATE TABLE (?:public\.)?(?P<table>\w+) \($")
ADD_PK = re.compile(
    r"ADD CONSTRAINT \w+ PRIMARY KEY \((?P<cols>[^)]*)\);")
ADD_FK = re.compile(
    r"ADD CONSTRAINT \w+ FOREIGN KEY \((?P<cols>[^)]*)\) "
    r"REFERENCES (?:public\.)?(?P<parent>\w+)\((?P<parent_cols>[^)]*)\)")
ALTER = re.compile(r"^ALTER TABLE (?:ONLY )?(?:public\.)?(?P<table>\w+)$")
COLUMN = re.compile(r"^\s{4}(?P<name>\w+) (?P<type>.+?)(?P<comma>,?)$")


class Table(object):
    def __init__(self, name):
        self.name = name
        self.columns = []          # [(name, type)] in dump order
        self.primary_key = []      # [column]
        self.foreign_keys = []     # [([child cols], parent, [parent cols])]

    def key_columns(self):
        keys = set(self.primary_key)
        for child_cols, _parent, _parent_cols in self.foreign_keys:
            keys.update(child_cols)
        return keys


def parse(text):
    """pg_dump text in, {table_name: Table} out. Only what an ERD needs is read."""
    tables = {}
    lines = text.splitlines()
    index = 0
    current_alter = None
    while index < len(lines):
        line = lines[index].rstrip()
        create = CREATE.match(line)
        if create:
            table = Table(create.group("table"))
            tables[table.name] = table
            index += 1
            while index < len(lines) and not lines[index].startswith(");"):
                body = lines[index].rstrip()
                # CONSTRAINT ... CHECK (...) may wrap over several lines; a column never
                # does, so anything that is not a bare `<name> <type>` at four spaces of
                # indent is skipped rather than parsed.
                column = COLUMN.match(body)
                if column and not body.lstrip().startswith("CONSTRAINT"):
                    kind = column.group("type").rstrip(",").strip()
                    table.columns.append((column.group("name"), kind))
                index += 1
            index += 1
            continue

        alter = ALTER.match(line)
        if alter:
            current_alter = alter.group("table")
            index += 1
            continue

        if current_alter and current_alter in tables:
            table = tables[current_alter]
            primary = ADD_PK.search(line)
            if primary:
                table.primary_key = [c.strip() for c in primary.group("cols").split(",")]
            foreign = ADD_FK.search(line)
            if foreign:
                table.foreign_keys.append((
                    [c.strip() for c in foreign.group("cols").split(",")],
                    foreign.group("parent"),
                    [c.strip() for c in foreign.group("parent_cols").split(",")],
                ))
        index += 1
    return tables


def project(table, keys_only):
    """The columns this table shows: every key column, plus its story columns."""
    if table.name not in STORY:
        raise SystemExit(
            "er_schema.py: table {!r} is in the database and not in STORY. Add it (with "
            "the columns that carry its story, or an empty tuple) rather than letting a "
            "new table go undrawn.".format(table.name)
        )
    keys = table.key_columns()
    wanted = set(keys)
    if not keys_only:
        for column in STORY[table.name]:
            if column not in dict(table.columns):
                raise SystemExit(
                    "er_schema.py: {}.{} is in STORY and not in the database. The schema "
                    "moved; fix the allowlist rather than drawing a column that is "
                    "gone.".format(table.name, column)
                )
            wanted.add(column)
    # Dump order, so the diagram reads in the order the table was written.
    return [(name, kind) for name, kind in table.columns if name in wanted]


def emit(tables, names, keys_only=False):
    """DDL for `names`, keys and foreign keys inlined into each CREATE TABLE."""
    chunks = []
    shown = set(names)
    for name in names:
        table = tables[name]
        columns = project(table, keys_only)
        body = ["    {} {}".format(column, kind) for column, kind in columns]
        if table.primary_key:
            body.append("    PRIMARY KEY ({})".format(", ".join(table.primary_key)))
        for child_cols, parent, parent_cols in table.foreign_keys:
            # A foreign key whose parent is not in this diagram would point at nothing.
            if parent not in shown:
                continue
            body.append("    FOREIGN KEY ({}) REFERENCES {}({})".format(
                ", ".join(child_cols), parent, ", ".join(parent_cols)))
        chunks.append("CREATE TABLE {} (\n{}\n);".format(name, ",\n".join(body)))
    return "\n".join(chunks) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("dump", nargs="?", default="-",
                        help="pg_dump --schema-only file, or - for stdin (default)")
    parser.add_argument("--out", required=True,
                        help="directory the per-diagram .sql files are written to")
    args = parser.parse_args(argv)

    text = sys.stdin.read() if args.dump == "-" else open(args.dump).read()
    tables = parse(text)
    if not tables:
        raise SystemExit("er_schema.py: no CREATE TABLE found — was that a pg_dump file?")

    written = []
    everything = sorted(tables)
    plan = [("overview", everything, True)]
    for name, members, context in CLUSTERS:
        plan.append((name, list(members) + list(context), False))

    for name, members, keys_only in plan:
        missing = [t for t in members if t not in tables]
        if missing:
            raise SystemExit(
                "er_schema.py: cluster {!r} names {} which the database does not have."
                .format(name, ", ".join(missing)))
        path = os.path.join(args.out, "er-{}.sql".format(name))
        header = "-- {}\n-- Generated by docs/diagrams/er_schema.py from pg_dump. Do not edit.\n".format(
            TITLES[name])
        with open(path, "w") as handle:
            handle.write(header + emit(tables, members, keys_only=keys_only))
        written.append((path, len(members)))

    for path, count in written:
        print("{}  {} tables".format(path, count))
    print("{} tables in the dump, {} drawn in the overview".format(
        len(tables), len(everything)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
