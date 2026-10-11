# Diagrams

Ten technical diagrams of this system, and the exact commands that produce them: five
entity-relationship diagrams generated from the live schema, and five pictures drawn for the README.
Their look is decided in one file, `style.json`, and both pipelines read it.

| Diagram | Files | How it is made |
|---|---|---|
| Entity relationships | `er-overview` + four clusters, `.mmd` and `.png` | generated — `pg_dump` → `er_schema.py` → **erdify** → **mermaid-cli**, themed from `style.json` |
| Architecture | `architecture.json` · `.readme.svg` · `.png` | drawn — `draw.py` |
| ETL pipeline | `etl-flow.json` · `.readme.svg` · `.png` | drawn — `draw.py` |
| AI evaluation | `evaluation-flow.json` · `.readme.svg` · `.png` | drawn — `draw.py` |
| Name ladder | `name-ladder.json` · `.readme.svg` · `.png` | drawn — `draw.py` |
| Schema at a glance | `schema-glance.json` · `.readme.svg` · `.png` | drawn — `draw.py` |

---

## 1. The ER diagrams — generated

```sh
docs/diagrams/build.sh            # rebuild the five .mmd and the five .png
docs/diagrams/build.sh --check    # change nothing; exit non-zero if anything is stale
```

Run it from anywhere; it needs the stack up (`docker compose up -d --wait`). Both tools run in
throwaway `--rm` containers as the invoking user, so nothing is installed on the machine, nothing
is added to any image in the stack, and no output arrives owned by root.

### Why it starts at the database rather than at model classes

**This project has no ORM models.** The schema lives in 50 hand-written Alembic migrations that
call `op.create_table`, and every query is SQL written through SQLAlchemy Core. There is no
`DeclarativeBase`, no `Mapped[...]`, no `__tablename__` anywhere under `api/src`. An ERD
generator that parses model classes therefore finds zero entities here — that is a fact about
this codebase, not a failure of the tool.

What erdify *can* read is SQL DDL, so the pipeline starts from the schema itself:

```
docker compose exec db pg_dump --schema-only
        │
        ▼
docs/diagrams/er_schema.py        parse; inline the keys; project each table down to
        │                         its keys plus the columns that carry its story;
        │                         split into one overview and four clusters
        ▼
docs/diagrams/ddl/er-*.sql        (generated — committed, so the diagram is reproducible
        │                          from the repo alone and drift is detectable)
        ▼
erdify --sql-dialect postgres --format mermaid
        │
        ▼
er-*.mmd  ──▶  mmdc -c er-theme.json -b white -s 3  ──▶  er-*.png
                     ▲
style.json ──▶ mermaid_theme.py ──▶ er-theme.json
```

**Why not the migrations, which need no database.** `alembic upgrade head --sql` also emits DDL
offline, but it emits the whole *history*: dozens of `ALTER TABLE` statements, several of them
`DROP CONSTRAINT`, replaying every intermediate shape of every table. A parser reading that file
sees each table as it was first created, not as it is now. `pg_dump` sees only the end state.

**What `er_schema.py` drops, and why it is safe.** CHECK constraints, indexes, triggers,
functions, sequences, extensions and psql meta-commands. None of them appear in an ER diagram,
and two of them are not SQL at all — pg_dump's `\restrict` line and its dollar-quoted plpgsql
bodies each stop erdify's parser dead. What is kept is columns, types, nullability, PRIMARY KEY
and FOREIGN KEY, **inlined into the `CREATE TABLE`**: pg_dump emits keys as separate
`ALTER TABLE … ADD CONSTRAINT` statements, and erdify reads those tables as having no keys at all.

**What it projects away.** All 33 tables with all their columns is unreadable —
`business_tax_row` alone carries eight industry code/name columns. So every table shows its keys
in full plus a short allowlist of story-carrying columns (`STORY` in `er_schema.py`). The
allowlist is checked against the dump both ways: a table in the database and not in `STORY`
raises, and a column in `STORY` and not in the database raises. Neither is silently skipped.

**Where the look comes from.** `mermaid_theme.py` maps the colour, font and size tokens in
`style.json` onto mermaid's `base` theme, the one theme whose variables are all honoured, and writes
`er-theme.json`. A table takes the colour that means «stored» everywhere else in these pictures.

### The five diagrams

| File | Tables | Reads as |
|---|---|---|
| `er-overview` | all 33 (plus Alembic's version table), **keys only** | the whole map, and where the clusters touch |
| `er-reference` | 12 + 1 context | five open-data name sources: a publication row per fetched file, a data row per record |
| `er-weather` | 5 | CWA forecast and observation, and the township→station table that joins them to a place |
| `er-product` | 13 + 2 context | circle, round, submission, and the audit trail of every factor that moved a weight |
| `er-ledger` | 3 + 7 context | `ingest_run` against the seven publication tables, the pgvector retrieval crib, and the value-check history |

*Context tables* appear in a cluster they do not belong to, because hiding the parent of a
foreign key would draw a column pointing at nothing. They are:

- `er-reference` borrows **township_station** — `reference_place.township_code` is a real FK.
- `er-product` borrows **forecast_reading** and **observation_reading** — `weight_contribution`
  pins each contextual factor to the exact reading it was computed from, with a five-column and
  a four-column composite FK.
- `er-ledger` borrows **all seven `*_publication` tables** — `ingest_run` has one nullable FK to
  each, and a CHECK allowing at most one of them to be set.

`alembic_version` appears in the overview only. It is Alembic's own bookkeeping and belongs to
none of the four clusters.

### Two things to know before reading a rendered ER diagram

- **A composite foreign key draws as one edge per column.** erdify emits five parallel edges
  from `weight_contribution` to `forecast_reading` and four to `observation_reading`, each
  labelled with its own column. That is five labels for one constraint. It is not five
  relationships, and the label on each edge is true.
- **The `.mmd` files carry no title.** erdify's Mermaid output ignores `--title`, so they are
  left exactly as it writes them — which is what makes `build.sh --check` a real drift check
  rather than a diff against something edited afterwards. The titles are in the table above.

### Drift

`build.sh --check` runs three checks and fails on any:

1. Re-derives the DDL from the live schema and diffs it against the committed `ddl/*.sql`. A
   migration that changed a table shows up here.
2. `erdify --check`, which regenerates each `.mmd` from its `.sql` and exits non-zero on a
   difference.
3. Re-derives the mermaid theme from `style.json` and compares it with the committed
   `er-theme.json`. A changed token shows up here as «stale».

It does not re-render the PNGs. Re-run `build.sh` after any migration or token change.

**Both tools are pinned** in `build.sh`: erdify by version (`ERDIFY_VERSION`, currently `0.12.1`)
and mermaid-cli by version and digest (`11.16.0`). Unpinned, a tool's own update would read as a
change to the schema or the look.

---

## 2. The five README pictures — drawn

```sh
python3 docs/diagrams/draw.py            # write every <name>.readme.svg
python3 docs/diagrams/draw.py --check    # change nothing; exit 1 if a committed SVG differs
python3 docs/diagrams/draw.py --labels   # print every label and the specification it is drawn from
python3 docs/diagrams/draw.py --png      # also rasterise each SVG to <name>.png at twice its size
```

`draw.py` needs only Python's standard library to write the SVGs. `--png` also needs Playwright's
chromium and a Noto Sans TC font file named in `UPTO_DIAGRAM_FONT`; the repository carries no full
CJK face, and without one the Latin and Chinese fall back to different fonts and every width
changes. `draw.py` refuses to rasterise without it rather than draw the wrong widths.

**Why they are drawn, not exported.** A README column is about 840 pixels wide. Each picture is
drawn on an 840-unit canvas, so its text sizes are the sizes a reader sees; no text is smaller than
12 px at that width.

**The look is `style.json`**: the colours, the font stack, the text sizes, the strokes, as design
tokens in the W3C Design Tokens Format (2025.10). No labels and no layout are in it. The colours
each mean one thing, the same in every picture: blue for public open data and its reference copy,
green for weather, vermilion for the product, grey for the database and what it stores, purple for
the scheduled pipeline (hues chosen to stay apart for the common colour-vision deficiencies:
Okabe–Ito, darkened where needed, with Paul Tol's purple for the pipeline),
and pale yellow with a heavy black border for alerts and models. A box takes a light tint of its
colour with the full colour as its border; a group's outline takes the colour, dashed. Every text
clears 4.5:1 and every border 3:1.

**The marks.** `architecture` carries the vendors' own marks, unaltered: a solid AWS frame with the
AWS mark, a dashed AWS EC2 frame, and Cloudflare, FastAPI, PostgreSQL, Airflow, Ollama and GitHub in
their own colours. Their sources and terms are in `marks/NOTICE.md`. nginx, the container registry
and Telegram are labelled boxes.

### Where each label came from

Every number and name was read out of the code or the database, not recalled. Each picture's
`.json` specification records what connects to what, and `draw.py --labels` prints every label with
the specification it is drawn from. For three of them, the sources behind the specification:

- **architecture** — `app/compose.yaml`, `app/api/Dockerfile`, `app/README.md`.
- **etl-flow** — `app/airflow/dags/*.py` (the `SOURCES` table carries the crons),
  `app/api/src/upto/ingest/`, `app/api/src/upto/api_common.py` for the read-time name ladder,
  and the live `ingest_run` table for the outcome counts.
- **evaluation-flow** — `app/api/src/upto/evaluate/run_round.py` and `score.py`,
  `app/api/src/upto/classify/examples.py` and `embed.py`, the reports in
  `app/evaluation/`, and `select embed_model, count(*) from example_embedding group by 1`.

The agreement figures (the share of names whose label matches the AI-drafted reference) come from the reports' own **Pooled** tables, and each report carries the
sha256 of the test set it was scored on; only reports with the same sha share a table.
