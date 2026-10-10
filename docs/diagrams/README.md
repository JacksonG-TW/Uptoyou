# Diagrams

Ten technical diagrams of this system — five generated entity-relationship diagrams and five drawn
pictures — and the exact commands that produced them. Nothing here is drawn from memory: the ER
diagrams are generated from the live schema, and every label on the drawn pictures was read out of
the source file named in its footer.

| Diagram | Files | How it was made |
|---|---|---|
| Entity relationships | `er-overview` + four clusters, `.mmd` and `.png` | generated — `pg_dump` → `er_schema.py` → **erdify** → **mermaid-cli** |
| Architecture | `architecture.json` · `.html` · `.png` | drawn — an archify specification, rendered and exported with headless chromium |
| ETL pipeline | `etl-flow.html` · `.png` | drawn — same |
| AI evaluation | `evaluation-flow.html` · `.png` | drawn — same |

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
er-*.mmd  ──▶  mmdc -b white -s 3  ──▶  er-*.png
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

`build.sh --check` runs two checks and fails on either:

1. Re-derives the DDL from the live schema and diffs it against the committed `ddl/*.sql`. A
   migration that changed a table shows up here.
2. `erdify --check`, which regenerates each `.mmd` from its `.sql` and exits non-zero on a
   difference.

It does not re-render the PNGs, so a stale PNG is not caught. Re-run `build.sh` after any
migration.

**erdify is pinned** (`ERDIFY_VERSION` in `build.sh`, currently `0.12.1`). Unpinned, the drift
check would eventually report the tool's own version bump as a schema change.

---

## 2. The three drawn diagrams — self-contained HTML

`architecture.html` · `etl-flow.html` · `evaluation-flow.html`

Drawn with archify (MIT, `tt-a1i/archify`, patched so the rendered page makes no external
request): each diagram is a small JSON specification — `architecture.json`, `etl-flow.json`,
`schema-glance.json` and the others beside them — rendered to one self-contained HTML file and
validated for crossings, label clearance and readability before it is exported to PNG.

**The five pictures the README shows — `architecture.png`, `etl-flow.png`, `schema-glance.png`,
`name-ladder.png`, `evaluation-flow.png` — are drawn by hand instead**, as `*.readme.svg` on an 840-unit canvas and rasterised at twice that
size. A README column is about 840 pixels wide, and archify's fixed text sizes left its labels
at 4–9 px there; drawn at the column's own width, every word in these five is 13 px or larger.
Their facts are the archify specifications' (`architecture.json`, `etl-flow.json`,
`schema-glance.json`, `name-ladder.json`, `evaluation-flow.json`), which stay the checked record of what connects to what. They are one set drawn for engineers rather than in the product's look: a white ground, black lines
and arrows, and a few colours that each mean one thing, the same thing in every chart — blue for
public open data and its reference copy, green for weather, vermilion for the product, grey for the
database and what it stores, purple for the scheduled pipeline (Okabe–Ito hues, which stay apart for
the common colour-vision deficiencies), and pale yellow with a heavy black border for alerts and
models — told from vermilion by lightness, since a darker amber looked the same as vermilion to
protan and deutan readers. A box takes a light tint of its
colour with the full colour as its border; a group's outline takes the colour, dashed. Every text
clears 4.5:1 and every border 3:1, measured on the PNGs. `architecture` is drawn in the same idiom with the vendors' own marks: a solid AWS frame with the AWS mark, a dashed AWS EC2 frame, and Cloudflare, FastAPI, PostgreSQL, Airflow, Ollama and GitHub in their own colours (marks/NOTICE.md). nginx, the container registry and Telegram are labelled boxes.

**Each file is one file.** No stylesheet, no webfont, no CDN script, no remote image — the
upstream skill's Google Fonts link and its two CDN export scripts were removed for exactly this
reason. The check:

```sh
grep -n 'https\?://' docs/diagrams/*.html
```

The only permitted hit is `xmlns="http://www.w3.org/2000/svg"`, which is an XML namespace
identifier and not a URL anything fetches. Verified with a real browser as well: loading each
page under Playwright makes **zero** non-`file://` requests and logs no console errors.

Chinese labels (店名 · 品牌名稱 · 登記名稱 · 統編 · 法人 · 行業代號) resolve through the local
font stack, with *Noto Sans TC* in it.

### Re-shooting the five README pictures

Each `*.readme.svg` is shot at twice its own size (1680 px wide) by headless chromium. Its text asks
for Helvetica and then `sans-serif`; map both to Noto Sans TC, or the Latin falls back to DejaVu and
every width changes. A fontconfig file with `<alias binding="strong">` entries preferring
`Noto Sans TC` for `sans-serif`, `Helvetica Neue`, `Helvetica` and `Arial` (and `<dir>~/.fonts</dir>`)
does it: load each SVG with `FONTCONFIG_FILE` pointing at it, a viewport of the SVG's own
`width × height` and `deviceScaleFactor: 2`, and screenshot it to the `.png` beside it.

### Re-shooting the PNGs

They are browser screenshots, at 1780px wide so the 10px annotations stay readable:

```sh
export LD_LIBRARY_PATH="$HOME/.local/micromamba/envs/web/lib:$LD_LIBRARY_PATH"
export FONTCONFIG_PATH="$HOME/.local/micromamba/envs/web/etc/fonts"
python3 - <<'PY'
import asyncio
from playwright.async_api import async_playwright

PAGES = ["architecture", "etl-flow", "evaluation-flow"]
HERE = "/absolute/path/to/app/docs/diagrams/"

async def main():
    async with async_playwright() as play:
        browser = await play.chromium.launch(args=["--no-sandbox"])
        page = await browser.new_page(viewport={"width": 1780, "height": 1200})
        for name in PAGES:
            await page.goto("file://" + HERE + name + ".html", wait_until="load")
            await page.wait_for_timeout(1000)
            await page.screenshot(path=HERE + name + ".png", full_page=True)
        await browser.close()

asyncio.run(main())
PY
```

The two environment variables are not optional on this machine: without `LD_LIBRARY_PATH`
chromium fails to start on `libnspr4`, and without `FONTCONFIG_PATH` every Chinese glyph renders
as a tofu box — which screenshots as a plausible-looking diagram with no readable Chinese in it.

### Where each label came from

Every number and name was read out of the code or the database, not recalled:

- **architecture** — `app/compose.yaml`, `app/api/Dockerfile`, `app/README.md`.
- **etl-flow** — `app/airflow/dags/*.py` (the `SOURCES` table carries the crons),
  `app/api/src/upto/ingest/`, `app/api/src/upto/api_common.py` for the read-time name ladder,
  and the live `ingest_run` table for the outcome counts.
- **evaluation-flow** — `app/api/src/upto/evaluate/run_round.py` and `score.py`,
  `app/api/src/upto/classify/examples.py` and `embed.py`, the reports in
  `app/evaluation/`, and `select embed_model, count(*) from example_embedding group by 1`.

The accuracy figures come from the reports' own **Pooled** tables, and each report carries the sha256
of the test set it was scored on; only reports with the same sha share a table.
