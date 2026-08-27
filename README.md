# Up to you

[English](README.md) | [繁體中文](README.zh-TW.md)

[![frontend](https://img.shields.io/badge/frontend-Vue%203%20(vendored)-4FC08D?logo=vuedotjs&logoColor=white)](https://vuejs.org/) [![backend](https://img.shields.io/badge/backend-FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/) [![db](https://img.shields.io/badge/db-PostgreSQL%2017-4169E1?logo=postgresql&logoColor=white)](https://www.postgresql.org/) [![vector](https://img.shields.io/badge/vector-pgvector-4169E1?logo=postgresql&logoColor=white)](https://github.com/pgvector/pgvector) [![orchestration](https://img.shields.io/badge/orchestration-Airflow-017CEE?logo=apacheairflow&logoColor=white)](https://airflow.apache.org/) [![AI](https://img.shields.io/badge/AI-gemma2%3A2b%20%2B%20arctic--embed2-000000?logo=ollama&logoColor=white)](https://ollama.com/) [![data](https://img.shields.io/badge/data-36%2C499%20places-555555)](#the-pipeline)

**A group decides one meal together, and a weighted pair of dice does the choosing fairly.** Every
factor that moved a place's odds is a stored row, pinned to the reading it came from, so the result
is an auditable decision rather than a number that appeared.

**Demo:** local (`docker compose up`) — cloud URL in October.

### Two things to try in three minutes

```sh
docker compose up -d --wait                                  # the stack, one command
docker compose exec api python -m upto.issue 1 Kevin         # a device token, printed once
#   → open localhost:8080, paste token + circle id, propose a place, roll
python3 probes/m2_freshness.py                                # what the ledger knows about freshness
```

The first walks the product end to end. The second reads the run ledger and prints, per source, how
long after a republication we are guaranteed to notice and how often the source actually
republishes — the pipeline explaining itself from its own records.

### 專案速覽

| | |
|---|---|
| **The idea** | Five friends, one meal, nobody wants to be the one who chose. The app chooses, and then shows its work. |
| **How it decides** | Weighted dice, not a ranking. Every factor multiplies the odds, an avoided category multiplies by zero, and the reveal panel names each factor beside the number it contributed. |
| **Data** | 7 published sources through 6 DAGs, 226 publications and 356 ledger rows so far, 36,499 Taipei places. |
| **Engineering** | Content-addressed ingest with an idempotent ledger; a dropped table replays from what the ledger kept; a three-layer name derivation; a RAG classifier with a frozen evaluation set. |
| **Measured** | Storing costs 15.0 s and a no-change day 1.6 s, so the short-circuit is priced. The local RAG classifier scores 66.0% against the hosted model's 60.5%. Categories now cover 9.70% of the city and rise per backfill. |
| **Why this stack** | One compose file, one database doing both relational and vector work, no service that cannot be run on a 2 GB instance. |

### 功能展示

Screenshots are not in this file yet. The surface is mid-rewrite — the shipping front end is a
vendored Vue 3 build and D104 replaces it with Vite + React 19 + Tailwind 4 — and a screenshot of a
screen about to be replaced would age badly. `localhost:8080` after the two commands above is the
honest version until then.

*Models run behind a compose profile: `gemma2:2b` generates, `snowflake-arctic-embed2` retrieves.
The front end shipping today is the vendored Vue 3 global build with no build step; it is being
rewritten on Vite + React 19 + Tailwind 4, **in progress**, and gets no badge until it is in the
repository.*

*This English page is canonical: where the two languages disagree, this one is right.*

A self-hosted app for a small group deciding where to eat. Open a round, propose places, roll two
dice — and read, on a reveal panel, exactly how the odds got that way. Every factor that moved a
place's weight is stored as its own row, pinned to the reading it was computed from, so the result
is an auditable decision rather than a number that appeared.

Behind it sits the part this repository is really about: six scheduled sources, content-addressed so
an unchanged file costs nothing, a run ledger where a no-change day is a recorded heartbeat, and
lineage from any reading back to the run that wrote it.

## Stack

- **API** — Python, FastAPI, SQLAlchemy 2.0, async end to end, 19 hand-written Alembic migrations
- **Database** — PostgreSQL 17 with the pgvector extension; Airflow's metadata is a second database in the same instance
- **Orchestrator** — Apache Airflow 3, LocalExecutor, same compose stack
- **Models** — Ollama behind a compose profile: three 3B-class generators under comparison (`gemma2:2b`, `qwen2.5:3b-instruct-q4_K_M`, `llama3.2:3b`) and three embedders for the retrieval crib (`bge-m3`, `qwen3-embedding:0.6b`, `snowflake-arctic-embed2`)
- **Front end** — Vue 3 global build; no build step, no node, no CDN. nginx serves the files.

## The pipeline

| DAG | Schedule (UTC) | Taipei | Source |
|---|---|---|---|
| `upto_weather_ingest` | hourly | hourly | CWA township forecast `F-D0047-061` + station observations `O-A0001-001` |
| `upto_place_reference_ingest` | `0 19 * * *` | 03:00 next day | 食藥署 食品業者登錄 — the restaurant reference list |
| `upto_brand_ingest` | `20 19 * * *` | 03:20 next day | 臺北市食材登錄平台 — company ↔ brand pairs |
| `upto_storefront_ingest` | `40 19 * * *` | 03:40 next day | 臺北市餐飲衛生分級評核 — the sign an inspector saw |
| `upto_business_status_ingest` | `0 20 * * *` | 04:00 next day | 商業登記-餐館業 — which registrations are dead |
| `upto_business_tax_ingest` | `20 20 * * *` | 04:20 next day | 財政部 全國營業(稅籍)登記 — tax name + industry code |

**The crons are UTC, and the quiet hours they aim at are Taipei's.** Airflow's
`core.default_timezone` is `utc` here, so the two columns are the same instant read on two
clocks — the daily sources fetch between 03:00 and 04:20 Taipei, one download at a time.

**A publication is identified by the hash of its bytes, not by a timestamp.** A stamp can move
while the data stands still, and stand still while the data moves. The content hash is the key;
the file's own stamp is kept beside it as a label, and where both exist they are compared every
run — a disagreement exits 2 and fails the task deliberately.

**The cheap half gates the expensive half.** The reference ingest fetches a 17 MB zip, hashes the
compressed bytes, and claims the publication with `insert … on conflict do nothing returning id`
— the *database* decides whether the content is new. Only then does anything decompress the
99 MB CSV inside (827,784 rows, of which the **36,499** Taipei restaurant rows are kept). The
file is monthly and the poll daily, so ~29 runs a month find nothing and must be silent successes.

**A run that wrote nothing is still a run.** Every attempt writes an `ingest_run` row, and
`no_change` and `failed` are different recorded outcomes — inferred from an absence they are
indistinguishable, which is how a broken source looks healthy for a week.

**Lineage is served to a model too.** Any reading traces to its publication, its content hash and
the run that wrote it, over MCP on stdio:

```sh
docker compose exec -T api python -m upto.lineage.mcp_server
```

Five tools answer: `run_history`, `run_detail`, `publication_detail`, `forecast_reading_source`,
`observation_reading_source`. A sixth, `explain_place_loss`, is listed **only in order to
refuse** — the honest trail runs into private per-member vetoes, and a tool that merely lacks a
feature today grows it the first time somebody finds it useful. A test asserts the refusal.

### The sixth source, landed

The tax registry is the widest file here: a 66 MB zip holding one ~320 MB CSV of **1,711,012 rows
— every registered business in the country.** Only rows whose 統編 already appears in the latest
reference publication are stored: **14,521 kept against 19,203 reference numbers, in about 15
seconds.** The other ~1.69M are never written — a storage decision, not an optimisation: a tax row
for a hardware store two hundred kilometres away answers nothing this app asks.

It publishes what nothing else did — the 營業人名稱 the tax office holds, and the **行業代號 the
business registered itself under**, an official category the shop chose rather than one a model
guessed. The four code/name pairs are stored positionally: the first is the primary trade, and
compacting the empty tail would silently promote a secondary one. Stored now, read by nothing yet.
One warning sits in the schema: `business_tax_row.address` is the **registered** address, not the
storefront — 6.2% of matched rows sit outside 臺北市 — and nothing may join on it.

## Names and categories

**A registered name is a legal entity, not a shop.** The reference list knows
安心食品服務股份有限公司; the people deciding where to eat know 摩斯漢堡. So a display name resolves at
read time down a ladder — **storefront sign → brand → registered name.** The sign wins: an inspector
recorded it against the same registry number, so that join needs no name matching at all (1,686 rows,
1,379 joining the current publication). The brand applies only where a company maps to exactly one
(188 of 266 join; a multi-brand company keeps its registered name, because nothing in either source
says which brand this site is). A 統編 the registry records as dead — and never alive — drops out of
the search typeahead, names elsewhere untouched.

**Categories are ten values, closed:** 麵食 · 飯食 · 小吃 · 火鍋 · 燒烤 · 日式 · 西式 · 早餐 ·
咖啡飲料 · 其他. An answer outside the list is **refused, never repaired** — coercing 拉麵 into 麵食
turns a wrong answer into a plausible one, and deletes the only step in the process that can fail.

Classification runs as a batch against a locally deployed quantized 3B model, off unless a backfill
is running (it peaks around 2.1 GB; the deployment target has 4). The model is asked the best name
the project holds — the same ladder — and every decided row records **the prompt version, the model
name, and the exact string that was asked.** A legal-entity verdict is written as a decided absence:
provenance present, category null, so re-runs never re-ask it. Batches commit as they go, so an
interrupted seven-hour pass resumes where it stopped.

**Set up to be measured, not asserted.** `evaluate/testset_v1.json` is a frozen, teacher-labeled set of
**200 names** — labels drafted by a frontier model and cross-checked by a second, so a score reads
"agreement with the teacher", never ground truth —, drawn deterministically — fixed seed, stratified by which layer of the ladder supplied
the name, floor of 30 per layer so the small sign and brand strata stay scorable. Frozen so scores
stay comparable across prompt versions, which carry a version string that changes with the text.

## Key technical decisions

Nine choices, each with what was rejected and the number that decided it. The full argument for
every one — and for the eighty-odd smaller ones — lives in the private design log; this is the
digest a reader of the code should have.

**1. Classification runs on a local 3B model; the cloud model is a yardstick, not a worker.**
*Chosen:* a quantized 3B generator on the same box as the database, batch-only, off unless a
backfill runs. *Rejected:* a hosted model as the classifier. *The number:* the free hosted tier
allows 500 calls a day, so 3,300 places take seven days; the local model does them in one night —
and the hosted model's score is kept, as the line the local ones are measured against.

**2. Missing knowledge is added as data, not as prompt text or weights.**
*Chosen:* a retrieval crib — labeled example names embedded into pgvector, the five nearest handed
to the model as worked examples. *Rejected:* another prompt revision; fine-tuning. *The number:*
the prompt revision (v4) *lost* points on the frozen set (gemma 51.5→49.5); retrieval on the same
set moved gemma2:2b 51.5→61.0 and llama3.2:3b 37.0→58.0, and qwen2.5:3b 51.0→48.5 — the same crib
reads as noise to one model, which is why the pairing is measured rather than assumed.

**3. Vector search is a Postgres extension, not a second service.**
*Chosen:* `pgvector` on the database already in the stack. *Rejected:* a dedicated vector store
(Pinecone, Milvus, Qdrant). *The number:* the crib is 537 rows across three embedders — thousands
at most — and the deployment target is a 2 GB-class instance; one image tag against one more
stateful service to run, back up and monitor.

**4. The evaluation set is frozen, stratified, and its authorship is stated.**
*Chosen:* 200 names, fixed seed, stratified over the three name layers with a floor of 30, labels
by a teacher model with a second model's cross-check, provenance recorded per row. *Rejected:*
scoring against live rows; owner-only labeling (planned, not executed — recorded as such). *The
number:* the frozen set caught a prompt that read better and scored worse, which is the only thing
a fixed set exists to do; every report carries the set's sha256 so two scores compare only when it
matches.

**5. A shop's name is resolved down a ladder — sign, then brand, then registered name.**
*Chosen:* three sources joined by registry number, precedence fixed, no fuzzy name matching.
*Rejected:* the registered name alone; string similarity across sources. *The number:* 40.2% of
registered names are legal-entity strings that name no shop at all; the sign join needs no matching
(1,686 rows, 1,379 joining the current publication); a trial of an outside geodata source
false-joined 46% on address alone and was dropped. Measured across sources: the sign differs
from the registered name on 93% of the rows that have one, and the brand table renames 57% of
the companies it covers — the ladder is doing work, not decoration.

*How far it reaches, measured over the whole current publication* — 36,499 rows, the same joins
the API uses at read time:

| Rung | Rows | Share | Of those, still names a company |
|---|---|---|---|
| sign (D78, site-level) | 1,379 | 3.8% | 3.3% |
| brand (D77, single-brand companies only) | 4,001 | 11.0% | 44.0% |
| registered (what is left) | 31,119 | 85.3% | 33.3% |

**The ladder reaches 14.7% of the city, and 33.3% of all rows still display a string that names a
company rather than a shop.** That is the honest state of it: where a sign exists the name is
right, and a sign exists for one row in twenty-six. The number is carried here rather than
smoothed because it is the argument for the next source, not against this one — each rung was
measured before it was believed, and this is the rung-by-rung version of the same discipline.
D92's derivation then splits the sign-less rows that would otherwise collide: 9,136 gain the
district-and-road bracket, 3,234 need the house number, and 22,750 are the only sign-less site of
their company and stay bare. Whether a place's rung is *stable* across publications is not
answerable yet — the sign and brand sources have each published once, and one publication yields
no interval to compare.

**6. Official industry codes decide only what they can, and that is one row in ten.**
*Chosen:* the tax registry's codes rule where unambiguous, the model takes the rest. *Rejected:*
codes as the classifier; ignoring codes entirely. *The number:* codes settle 10.9% of city rows;
a coffee chain's 245 branches register under a wholesale code, so a code alone would mislabel every
one of them. The join itself is safe — 99.78% name agreement once the legal-form suffix is
stripped — and the address is not: 89.8% differ, 13.7% are registered outside the city.

*Measured again on the set that is actually scored, which is a harder test than the city-wide
join* — the 200-row frozen evaluation set, against the best model configuration on record
(gemma2:2b + retrieval, 66.0% pooled; the hosted yardstick is 60.5%):

- **142 of 200 rows join a tax row**, and **75 of those 142 are a chain's HQ registry number** —
  so the guardrail that forbids ruling a multi-site company non-food by code alone is the
  majority case here, not an edge case.
- **The two largest codes settle nothing by construction.** 餐廳 covers 39 rows and the teacher
  spread them over four labels; 麵店、小吃店 covers 16 and straddles two categories the code
  cannot split.
- **The upper bound on a code rule is +13 rows of 200, and it is an oracle bound** — each code's
  label was chosen by looking at the answers it would then be scored against. Strip the codes
  that appear on fewer than four rows, where a "majority label" is one or two observations, and
  the defensible upside is **+4 rows, 2 points**.
- The instructive row is 茶葉批發: a wholesale code, all four rows a chain's HQ number, and three
  of the four are drinks shops. The code describes the company's trade; the shop is still a shop.
  A non-food verdict there would have been wrong three times in four, which is the guardrail
  earning its place rather than merely being cautious.

So the honest form of this decision is that the codes **sharpen** the pipeline and cannot replace
the classifier — the same conclusion the city-wide join reached, now with the model's own score on
the other side of the comparison. Which codes may decide, and what they may decide, is a mapping
that has to be argued from the registry's semantics rather than fitted to 200 rows.

**7. Every source is content-addressed and its no-change days are recorded.**
*Chosen:* a publication row per fetched file (hashed, deduplicated), a data row per record, and a
run ledger where a no-change day writes a heartbeat. *Rejected:* overwrite-in-place; schedules
guessed to match each file's cadence. *The number:* six daily DAGs, most days storing nothing and
recording that — a silently broken source and a quiet one become distinguishable, which is the
absence-vs-failure problem the ledger exists to solve. Proven, not assumed: every source is
idempotent on identical bytes (every column of every table compared, `tests/test_ingest_idempotency.py`),
and the no-change path costs 1.6 s against 15–19 s for a real store.

*Measured on the schedule itself* — 8 days, 332 rows of the run ledger against 361 Airflow task
instances, nothing instrumented and no column added:

| Source | Store p50 | No-change p50 | Ledger rows | Tasks succeeded |
|---|---|---|---|---|
| CWA township forecast | 2.99 s | 1.85 s | 149 | 162 / 164 |
| CWA station observation | 3.09 s | 0.31 s (n=1) | 149 | 164 / 164 |
| FDA 餐飲場所 reference | none yet | 1.88 s | 5 | 9 / 9 |
| 食材登錄 brands | 0.57 s | 0.96 s | 8 | 6 / 6 |
| 衛生評核 signs | 0.31 s | 0.43 s | 7 | 6 / 6 |
| 商業登記 status | 25.03 s | 2.09 s | 7 | 6 / 6 |
| 營業稅籍 registry | 12.95 s | 3.58 s | 7 | 6 / 6 |

Three things the schedule shows that a single run cannot. **The no-change day is 3.6× cheaper
than a store on the largest source** (3.58 s against 12.95 s) and 12× on the registry roster —
which is the whole of the claim-before-parse short-circuit, priced. **Orchestration costs a flat
1.2 s a task** (median, every source, from the gap between Airflow's duration and the runner's
own ledger interval): the DAG shells the ingest out to a subprocess, and that price is the same
whether the source takes half a second or twenty-five. **The scheduler is not the bottleneck** —
queue latency is 0.05 s at p50 and 4.2 s at its worst across all 361 task instances. What none of this
answers is the fetch / parse / store split: nothing records it, and measuring it would mean
per-phase timers and a schema to hold them.

*And the freshness bound, derived from the same ledger rather than from each source's claimed
cadence* — how long after a source republishes we are guaranteed to have noticed (ours, bounded
by the poll) plus how often it actually republishes (theirs, observed):

| Source | Detected within | Republishes every | So the data is |
|---|---|---|---|
| CWA township forecast | 62 min | 4.3 h median, 8.1 h worst | at most 9.1 h old |
| CWA station observation | 62 min | 60 min median, 62 min worst | at most 2.1 h old |
| 營業稅籍 registry | 24.0 h | 24.0 h median, 36.2 h worst | at most 2.5 d old |
| FDA 餐飲場所 reference | 24.0 h | insufficient history: 1 publication | not yet derivable |
| 食材登錄 brands | 24.0 h | insufficient history: 1 publication | not yet derivable |
| 衛生評核 signs | 24.0 h | insufficient history: 1 publication | not yet derivable |
| 商業登記 status | 24.0 h | insufficient history: 1 publication | not yet derivable |

**The four incomplete rows are the honest state, not a gap in the work.** A source seen once has
published once in this history, and *n* publications yield *n−1* intervals; the cell fills itself
as the DAGs run. What it will not do is borrow the number the publisher advertises — the roster
calls itself monthly and the tax extract is cut monthly, and neither is something this pipeline
observed. A cell sourced from a webpage would wear the same formatting as the measured seconds
beside it and mean something entirely different. The half that *is* ours is a real bound and
holds for all seven: no poll was missed in the window, and the longest stretch with no successful
run was 62 minutes on the hourly sources and one day on the daily ones.

**8. The cloud serves; the home box computes; the ledger is the clock.**
*Chosen:* a small EC2 instance runs the API and database; model batches run on a home box and land
through the same ingest ledger. *Rejected:* a resident model on EC2; all-cloud batches. *The
number:* the API stack sits at ~1.6 GB resident without the model. The home box's GPU — 8 GB, holding
the 2B generator and the embedder resident together — takes a RAG-shaped batch at **1.27 s a
name**, measured over one district's 1,318 rows from the database's own timestamps rather than a
stopwatch. The same batch on the box's CPU alone was 12–19 s a name.

*Then measured again, because the first measurement was of the wrong thing.* At 1.27 s a name the
GPU sat at 0–47% utilisation and a quarter of its power cap: the card was waiting, not computing.
Timing each call separately found the reason — a round trip with no model work costs 48 ms, but
every request carries ~475 ms of fixed cost that scales with **nothing**: not the input length, not
the output length, not the link. Two calls per name, so ~950 ms of the 1,270 was a cost paid per
*request*.

**So the fix was to make fewer requests, not faster ones.** The retrieval crib embedded one name per
call; a commit batch of 25 names now embeds in one call, and that half went from 0.481 to 0.045 s a
name — **10.8×**, measured twice on the same 100 names. *Rejected:* issuing several names
concurrently, which measured 2.6× on the generation half and saturated at four in flight — declined
because a pass commits every 25 rows and resumes at the first undecided one, and N requests in
flight is both N connections that can drop and an end to that clean frontier. A dropped connection
had already killed one pass at row 400 of 3,324; it is now retried three times, and the count is
printed so a flaky link reads as a number rather than as a slow night.

**What the batched pass has not yet shown is a faster pass, and that is the current state rather
than a pending edit.** A 2,912-row run began at 0.92 s a name — batching doing exactly what the
probe said — and then degraded steadily to about 2.0, finishing at **1.356 s a name overall**, which
is worse than the un-batched 1.27. The degradation is monotonic in elapsed time and its cause is
not yet known; nothing in the loop grows with progress, the crib is a fixed 537 rows, rows are
updated by primary key, and the run recorded **zero** dropped connections across 2,912 calls. The
comparison with 1.27 is also confounded: that figure came from a 28-minute pass, which may simply
have been too short to reach whatever this is. **So no whole-city projection is carried here.** The
per-call measurements above are direct A/B tests and stand; the pass-level number will be stated
when the curve is explained rather than averaged.

**9. Substring search stays a sequential scan; the trigram index was measured and rejected.**
*Chosen:* leave the typeahead's `ILIKE '%q%'` as it is. *Rejected:* `pg_trgm` + GIN on the three
searched columns; rewriting to the similarity operator. *The number:* the index changed the plan
for 0 of 31 realistic queries and left p50 at 311 → 324 ms, because the predicate ORs a base
column against two lateral outputs so the filter cannot reach the index — and because the
cluster's deterministic `C` locale makes `pg_trgm` emit no trigrams for 96.2% of the names. The
similarity rewrite returned zero rows for every CJK query and was refused. The scan was never the
cost: the reference table is ~1% of the query's buffers; a per-row lateral brand lookup executed
35,533 times per keystroke is 93%, and expressing it as one grouped join is 61× fewer buffers
with a provably identical result — a separate, pending change.

## Diagrams

Four views of the same system, in `docs/diagrams/` — each PNG has a self-contained source
beside it (`.html` for the drawn ones, `.mmd` for the ER set), no external request in any of them:

- **Architecture** — `architecture.png`: the compose stack, what is published, and the
  deployment intent (the cloud serves, the home box computes, the run ledger is the clock).
- **ETL pipeline** — `etl-flow.png`: six sources, six DAGs, the one content-addressed path they
  all take, the run ledger's three outcomes, and the read-time name ladder.
- **AI evaluation** — `evaluation-flow.png`: the frozen set, the pgvector crib, the four
  candidates, and what the set measured.
- **ER diagrams** — `er-overview.png` is all 26 tables; the readable ones are the four clusters,
  `er-reference.png` · `er-weather.png` · `er-product.png` · `er-ledger.png`. Generated from the
  live schema by `erdify` (`docs/diagrams/build.sh`); `build.sh --check` fails when the schema
  and the committed diagrams disagree.

## Privacy

**Authorship dies at the close, in the database.** Closing a round fires a trigger that nulls
`proposal.member_id` for that round, in the transaction that makes the result durable. A trigger
rather than application code, because a manual close over SQL, a fix-up script or a second code path
would each leave authorship behind and none would error. Nothing on the live stream carries a member.

## Quick start

```sh
cp .env.example .env      # names only — the comments state the shape of every value
docker compose up -d --wait
curl -s localhost:8080/health   # {"status":"ok","database":"reachable"}
```

- **`localhost:8080`** — the app (`UPTO_HTTP_PORT`), the only port the product publishes; the API
  and the database are reachable only over the compose network.
- **`localhost:8081`** — the Airflow UI (`AIRFLOW_HTTP_PORT`), user `admin`.
- The weather ingest needs a free CWA Open Data key (opendata.cwa.gov.tw), read once at init into a
  Fernet-encrypted Airflow Connection — never from the environment, never into XCom or a rendered
  template field. The five open-data files need no credential. New DAGs arrive **paused**
  (`airflow dags unpause <dag_id>`).

Run an ingest by hand — `0` stored or no change, `1` the source failed, `2` the version signals
disagree — or bring the model up for a backfill:

```sh
docker compose exec api python -m upto.ingest.run_places
docker compose exec api python -m upto.ingest.run_business_tax

docker compose --profile model up -d ollama
docker compose exec ollama ollama pull qwen2.5:3b-instruct-q4_K_M
docker compose exec api python -m upto.classify.run 63000010   # exit 3 = model absent, nothing written
```

## Tests

32 test files. Fetch, hash and parse are unit-tested with no network and no database, which is what
keeps the DAGs thin — they supply only *when* and *with which database*:

```sh
python3 api/tests/test_cwa_ingest.py    # and test_fda_ingest, test_fia_ingest, test_dice_table,
python3 api/tests/test_weight_fold.py   # test_classify, test_web_surface, test_evaluate_draw …
```

Integration tests build and drop their own database, in the test-only service that holds the
owner's credential — never in `api`, which connects as a role that cannot `create database`:

```sh
docker compose run --rm tests python /srv/tests/test_place_ingest_integration.py
docker compose run --rm tests python /srv/tests/test_business_tax_integration.py
```

## Scope

Taipei only — twelve townships, one city's open data, addresses normalised at the ingest boundary
because the same government file spells the city two ways. Sized for one small group: one API
worker, live room state in memory, five friends rather than five thousand. A portfolio project,
developed in a private repository and extracted here after every merge, so the commit messages
carry the reasoning behind each change.
