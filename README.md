-->

# Up to you

[English](README.md) | [繁體中文](README.zh-TW.md)

[![frontend](https://img.shields.io/badge/frontend-React%2019%20%2B%20Vite-61DAFB?logo=react&logoColor=black)](https://react.dev/) [![backend](https://img.shields.io/badge/backend-FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/) [![db](https://img.shields.io/badge/db-PostgreSQL%2017-4169E1?logo=postgresql&logoColor=white)](https://www.postgresql.org/) [![vector](https://img.shields.io/badge/vector-pgvector-4169E1?logo=postgresql&logoColor=white)](https://github.com/pgvector/pgvector) [![orchestration](https://img.shields.io/badge/orchestration-Airflow-017CEE?logo=apacheairflow&logoColor=white)](https://airflow.apache.org/) [![AI](https://img.shields.io/badge/AI-gemma2%3A2b%20%2B%20arctic--embed2-000000?logo=ollama&logoColor=white)](https://ollama.com/) [![data](https://img.shields.io/badge/data-35%2C965%20places-555555)](#the-pipeline) [![deploy](https://img.shields.io/badge/deploy-EC2%20%2B%20Cloudflare-FF9900?logo=amazonaws&logoColor=white)](#deployment)

**A group decides one meal together, and a weighted pair of dice does the choosing fairly.** Every
factor that moved a place's odds is a stored row, pinned to the reading it came from, so the result
is an auditable decision rather than a number that appeared.

**Demo:** `https://uptoyou.jacksong-tw.com` — one small EC2 instance in Tokyo behind Cloudflare, running exactly what `docker compose up` runs here. Local: the three commands below.

### Two things to try in three minutes

```sh
docker compose up -d --wait                                  # the stack, one command
docker compose exec api python -m upto.issue 1 Kevin         # a device token, printed once
#   → open localhost:8080, paste token + circle id, propose a place, roll
docker compose exec db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "select source, outcome, count(*), max(finished_at) from ingest_run group by 1, 2 order by 1, 2"'
```

The first walks the product end to end. The second reads the run ledger: per source, how many runs
stored something, how many found nothing new, how many failed, and when the last one finished. A
source that goes quiet shows up as a stale `max`, not as an absence.

### 專案速覽

| | |
|---|---|
| **The idea** | Five friends, one meal, nobody wants to be the one who chose. The app chooses, and then shows its work. |
| **How it decides** | Weighted dice, not a ranking. Every factor multiplies the odds, an avoided category multiplies by zero, and the reveal panel names each factor beside the number it contributed. |
| **Data** | 7 published sources through 6 ingest DAGs (nine scheduled in all). **On the launch instance:** 35,965 Taipei places, 25,031 of them with a generated category. **The pipeline's history is longer than the instance's**, so the publication counts are given per host and with their start dates: the development database holds **30 publications from the five reference sources since 2026-08-11** (the place source began that day; the other four on 2026-08-14, when D77, D78, D81 and D85 landed) and **837 from the hourly weather feed since 2026-08-11**; the launch instance, built on 2026-09-04, holds 5 and 69. Publication rows are kept for ever by design — they are the ledger the freshness probe reads — so the weather figure is a running count rather than a size. |
| **Engineering** | Content-addressed ingest with an idempotent ledger; a dropped table replays from what the ledger kept; a three-layer name derivation; a RAG classifier with a frozen evaluation set. |
| **Measured** | Storing costs 15.0 s and a no-change day 1.6 s, so the short-circuit is priced. Four local models on one frozen set: 72.0 · 71.0 · 70.5 · 65.5 (v7, 2026-08-30); the hosted yardstick read 60.5 on the first set. The whole city is classified (36,014 rows, 2026-09-03). The 2 GB instance holds its nightly work with 398 MB to spare, after a week that started at 49. |
| **Why this stack** | One compose file, one database doing both relational and vector work, no service that cannot be run on a 2 GB instance — and it is running on one. |

### 功能展示

Five screens: home · device · 這一餐 (tonight's avoided categories, as a menu with section marks) ·
round (propose, then roll) · reveal (the dice stop, then the winner's odds are itemised, factor by
factor). One slim bar on every inner screen, back on the left, three links on the right. No
screenshots are kept in this file on purpose: the demo above is the current build, and a picture of a
screen is stale the day after it is taken.

*Models run behind a compose profile on the home box: `gemma2:2b` generates, `snowflake-arctic-embed2`
retrieves. The front end is Vite + React 19 + Tailwind 4 + shadcn/ui, built inside the proxy image
by `npm ci && npm run build`; the served bundle fetches nothing at runtime.*

*This English page is canonical: where the two languages disagree, this one is right.*

A self-hosted app for a small group deciding where to eat. Open a round, propose places, roll two
dice — and read, on a reveal panel, exactly how the odds got that way. Every factor that moved a
place's weight is stored as its own row, pinned to the reading it was computed from, so the result
is an auditable decision rather than a number that appeared.

Behind it sits the part this repository is really about: six scheduled sources, content-addressed so
an unchanged file costs nothing, a run ledger where a no-change day is a recorded heartbeat, and
lineage from any reading back to the run that wrote it.

## Stack

- **API** — Python, FastAPI, SQLAlchemy 2.0, async end to end, 42 hand-written Alembic migrations
- **Database** — PostgreSQL 17 with the pgvector extension; Airflow's metadata is a second database in the same instance. Five login roles, one per boundary: the API, the ingests, the nightly erasure, the backup, and the owner — which only the one-shot migration container ever holds
- **Orchestrator** — Apache Airflow 3, LocalExecutor, same compose stack — one task at a time, the log server off, healthchecks every two minutes (see decision 10)
- **Models** — Ollama on the home box's 8 GB card, reached through a relay: four generators under comparison (`gemma2:2b`, `llama3.2:3b`, `qwen2.5:7b-instruct`, and `qwen2.5:3b-instruct` for evaluation only — its licence is non-commercial) and three embedders for the retrieval crib (`bge-m3`, `qwen3-embedding:0.6b`, `snowflake-arctic-embed2`). The scheduled pair is `gemma2:2b` × `snowflake-arctic-embed2`
- **Front end** — Vite + React 19 + Tailwind 4 + shadcn/ui, built inside the proxy image; nginx serves the bundle and terminates TLS with a Cloudflare Origin CA certificate. No CDN, no runtime fetch; two subset fonts ship with the bundle and a pre-commit gate proves they cover every string a member can read.

## The pipeline

| DAG | Schedule (UTC) | Taipei | Source |
|---|---|---|---|
| `upto_weather_ingest` | hourly | hourly | CWA township forecast `F-D0047-061` + station observations `O-A0001-001` |
| `upto_place_reference_ingest` | `0 19 * * *` | 03:00 next day | 食藥署 食品業者登錄 — the restaurant reference list |
| `upto_brand_ingest` | `20 19 * * *` | 03:20 next day | 臺北市食材登錄平台 — company ↔ brand pairs |
| `upto_storefront_ingest` | `40 19 * * *` | 03:40 next day | 臺北市餐飲衛生分級評核 — the sign an inspector saw |
| `upto_business_status_ingest` | `0 20 * * *` | 04:00 next day | 商業登記-餐館業 — which registrations are dead |
| `upto_business_tax_ingest` | `20 20 * * *` | 04:20 next day | 財政部 全國營業(稅籍)登記 — tax name + industry code |
| `upto_preference_erasure` | `0 21 * * *` | 05:00 next day | deletes every per-meal preference row a roll did not pin |
| `upto_weather_retention` | `40 21 * * *` | 05:40 next day | deletes unpinned weather readings older than ninety days |
| `upto_db_backup` | `20 22 * * *` | 06:20 next day | `pg_dump` to S3 after both deletions, thirty kept |

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

**Categories are thirteen values, closed:** 麵食 · 飯食 · 小吃 · 火鍋 · 燒烤 · 日式 · 西式 · 早餐 ·
咖啡飲料 · 便利商店 · 台菜 · 素食 · 其他 (ten until 2026-08-30; the eleventh came from a measured loss —
convenience stores were the largest single miss on the frozen set — and the last two from a look at
what 其他 was hiding). An answer outside the list is **refused, never repaired** — coercing 拉麵 into
麵食 turns a wrong answer into a plausible one, and deletes the only step in the process that can
fail. The next change is already ruled: 素食 stops being a category and becomes an attribute a place
carries (素食麵館 = 麵食 + 有素), because «I cannot eat here» is a requirement on the table and not a
discount, and the set returns to twelve.

Classification runs as a batch against a locally deployed quantized 3B model, off unless a backfill
is running (it peaks around 2.1 GB; the deployment target has 4). The model is asked the best name
the project holds — the same ladder — and every decided row records **the prompt version, the model
name, and the exact string that was asked.** A legal-entity verdict is written as a decided absence:
provenance present, category null, so re-runs never re-ask it. Batches commit as they go, so an
interrupted seven-hour pass resumes where it stopped.

**Set up to be measured, not asserted.** `evaluate/testset_v3.json` is a frozen, teacher-labeled set of
**200 names** — labels drafted by a frontier model and cross-checked by a second, so a score reads
"agreement with the teacher", never ground truth — drawn once, deterministically: fixed seed,
stratified by which layer of the ladder supplied the name, floor of 30 per layer so the small sign
and brand strata stay scorable. The draw has never been re-run; v1 and v2 are the same 200 rows
relabelled under two rulings, kept because rounds scored against them are on the record, and every
report names its set and its sha256 so two numbers compare only when both match.

## Key technical decisions

Eleven choices, each with what was rejected and the number that decided it. The full argument for
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

*The current table* — prompt v7, thirteen categories, `testset_v3`, the same crib (`snowflake-arctic-embed2`,
five neighbours), every round on the home box through the same relay the DAG uses:

| model | licence | pooled accuracy (200 rows) |
|---|---|---|
| `qwen2.5:7b-instruct` | Apache-2.0 | **72.0%** |
| `gemma2:2b` | Gemma terms | 71.0% |
| `llama3.2:3b` | Llama 3.2 community | 70.5% |
| `qwen2.5:3b-instruct` | research licence — evaluation only | 65.5% |

These four are the plain rounds, `app/evaluation/round_<model>_v7-rag-2026-08-30_arctic.json.report.md`
— named exactly because the same directory holds `_brandcrib` variants of two of them, run on
2026-09-04 with an authored brand crib added, which read 2.5 to 4.0 points higher and are a
different experiment rather than a better score for the same one.

Three models inside two points of each other, one of them three times the cost per row; the scheduled
pass kept `gemma2:2b`. The hosted yardstick read 60.5% on the first set (2026-08-14) and has not been
re-run on the third, so the two numbers are not compared in one sentence.

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
join* — the 200-row frozen evaluation set. The accuracy quoted beside it when this was written was
**66.0%**, `gemma2:2b` with retrieval on `testset_v1` under prompt v5
(`round_gemma_v5-rag-2026-08-15_arctic.json.report.md`); the same model and configuration now reads
**71.0%** on `testset_v3` under v7, in the table above. **The join figures below are unaffected and
that is not luck**: D82 drew the 200 rows once and froze them, and v1, v2 and v3 differ by
relabelling under a ruling only — the same rows in the same order — so «142 of 200 join a tax row»
is a fact about the draw, not about the prompt that scored it:

- **142 of 200 rows join a tax row, and 75 of those are a chain's HQ registry number** — the
  guardrail against ruling a multi-site company non-food by code alone is the majority case.
- **The upper bound on a code rule is +13 rows of 200, and it is an oracle bound**; strip the codes
  seen on fewer than four rows and the defensible upside is **+4 rows, 2 points**. The instructive
  row is 茶葉批發: a wholesale code on four HQ numbers, three of them drinks shops — a non-food
  verdict there would have been wrong three times in four.

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
number:* the whole serving stack — API, database, proxy and Airflow — sits at 942 MiB at rest on the
2 GB instance (2026-09-07, after decision 10). The home box's GPU — 8 GB, holding
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

**The pass then slowed as it ran, and the cause was found on the box rather than guessed.** A
2,912-row run began at 0.92 s a name and degraded steadily to about 2.0; four townships on two
builds bent the same way (1.7× first-to-last). Sampling the model server's memory during a round
showed it keeping one saved prompt state per distinct prompt, unbounded — about 100 MB per request
for the 2B model — until the 8 GB box killed it once. The fix is to unload the model every N rows
(N per model, 25 for `gemma2:2b`), which costs a ten-second reload and holds the curve level: the
city re-pass ran 36,014 rows in 10.5 h with five flat curves, and the one district that had
contradicted the model no longer does.

**Where those rows live, and why two hosts disagree.** The classification runs where the GPU is,
which is neither the launch instance nor the development box's own CPU, so the classified rows are
*copied* to the instance rather than produced on it. Each host also runs the reference ingest for
itself, and the published file moves: on 2026-09-07 the instance's own publication no longer
carried 532 of the numbers the classification had been run against — closed or deregistered since —
and those rows were deleted there, because the newest publication is the truth about what is open
and a place the source no longer lists is one the product cannot show. So **the instance holds
35,965 reference places and the development database 36,497 — the same unit on both sides, and
distinct from the 36,499 rows the publication itself carries, since two of those rows share a
registered number — and that gap is the source moving, not a failure**. It closes on the next city pass or when the classifier's output is shipped nightly
instead of by hand.

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

**10. The 2 GB instance was too small for its own nightly work, and the fix was measured before it
was chosen.** *Chosen:* stream the one ingest that held its whole file in memory, then shrink Airflow
with four settings and a memory limit that actually bites. *Rejected:* a bigger instance first (ruled,
then refused by the account's plan); a swap file (turns a crash into a twelve-hour crawl); tuning
without a table. *The numbers, in the order they arrived, over 2026-09-04 to 09-07:* the first night, eight DAGs unpaused in one
loop wedged the box while every cloud health check stayed green; walked one at a time, the registry
roster left **49 MB** free against a 150 MB floor; the roster ingest was found holding 209,472 row
objects until the write ended — streamed in 5,000-row chunks its peak fell **172 → 77 MB** with rows
identical; then the second night showed the real cost was Airflow itself at ~1.35 GB idle, and that
two tasks in the same minute crawled the box for twelve hours with no OOM line. Measured on a scratch
stack: one task at a time, the log server off, one parser process and healthchecks every 120 s take
the stack **1,131 → 1,009 MiB** at rest — and the box's mysterious 80% idle CPU was the healthcheck
itself, a **7.4-s** CLI cold start every 20 s on two services. On the instance, every scheduled job
then ran one after another with the worst reading at **398 MB** free and the kernel's kill counter at
zero. The instance stayed small.

**11. The live stream sends a heartbeat because the proxy in front of it cuts silence.** *Chosen:* an
SSE comment line every 25 s, invisible to every screen. *Rejected:* an unproxied hostname (gives up
the shield the domain exists for); reconnect-and-hope. *The number:* through Cloudflare, a stream
silent for 130 s was **cut** and a real event afterwards delivered nothing; direct to the origin the
same stream stayed open and delivered — same code, same seconds, side by side, twice. With the
heartbeat the same probe through the same hostname reads open and delivering. A circle that has said
nothing for two minutes is the normal case for this product, so this was a launch blocker and not a
polish item; the comment line carries no timing a member could read (see Privacy).

## Deployment

**The box pulls; nothing reaches in.** One EC2 `t3.small` in Tokyo runs `docker compose up` on the
public extract of this repository — the same compose file, the same images, the same migrations. It
fetches a merge itself; no CI system holds a way into it. Cloudflare fronts the product hostname in
Full (strict) mode with an Origin CA certificate on nginx, and the security group admits 443 from
Cloudflare's published ranges only. The GPU box at home does the model work (decision 8) and reaches
nothing; classified rows travel outward to the instance. **Backups:** a nightly `pg_dump` to S3 under
a read-only role, thirty kept, swept only after a successful upload; the restore drill on the 338 MB
development database took 3.7 s to dump and 9.4 s to restore, counts identical; the instance's own
dump is 31.2 MiB in 12 s. The launch runbook's pass criterion was one full ingest cycle stored on the
box the same day, with the memory numbers held — not «it booted».

## Gates and review

Every commit passes six local gates in a pre-commit hook. Five need only the standard library, so a
clone needs no toolchain to commit: a secret scan, the `app/` boundary (nothing private leaks into
the extract), the font subset against every member-readable string, the server's own copy drawable
in the shipped fonts, and the hazard register's numbering. The sixth reads every staged Python file
with `ruff` and refuses syntax errors and real faults — undefined names, unused imports, a
`.format` whose arguments go nowhere — and nothing about formatting; on a machine without `ruff` it
names what is missing, checks nothing and lets the commit through, because the tool is the gate's
dependency rather than the repository's. Above the gates sit two readers
who did not write the change: the surface is judged from the served page and the wire, with its own
harnesses (a five-agent walkthrough, a load ladder, a silence test that requires delivery and not
merely an open socket); and every backend diff is read against the rulings it cites and the tests it
names before a build is named a candidate. Seven of nine red findings on one day were the instrument
measuring itself, which is why the harnesses now write down what would make them report a defect if
the product were fine.

## Diagrams

Four views of the same system, in `docs/diagrams/` — each PNG has a self-contained source
beside it, and none of them makes an external request. **The three drawn ones were redrawn from the
code as deployed on 2026-09-07 and every box in them names something that exists**: the compose
services, the eleven DAG ids and their crons, the seven publication tables, the ports the proxy
actually listens on. Their editable source is the `.json` beside each — `architecture.json`,
`etl-flow.json`, `evaluation-flow.json` — with the `.html` a standalone rendering of it; the ER set
keeps its `.mmd` and regenerates from the live schema (`docs/diagrams/build.sh --check` reports
drift for that set, and does not touch the drawn three):

- **Architecture** — `architecture.png`: the compose stack as served, the instance behind
  Cloudflare, the home box behind its relay, the nightly dump to S3.
- **ETL pipeline** — `etl-flow.png`: seven sources, six DAGs (the weather publisher's forecast and
  observation are two sources on one fetch), the one content-addressed path they
  all take, the run ledger's three outcomes, and the read-time name ladder.
- **AI evaluation** — `evaluation-flow.png`: the frozen set, the pgvector crib, the four local
  candidates and the hosted yardstick, and the two human gates around a build.
- **ER diagrams** — `er-overview.png` is all 26 tables; the readable ones are the four clusters,
  `er-reference.png` · `er-weather.png` · `er-product.png` · `er-ledger.png`. Generated from the
  live schema by `erdify` (`docs/diagrams/build.sh`); `build.sh --check` fails when the schema
  and the committed diagrams disagree.

## Privacy

**Authorship dies at the close, in the database.** Closing a round fires a trigger that nulls
`proposal.member_id` for that round, in the transaction that makes the result durable. A trigger
rather than application code, because a manual close over SQL, a fix-up script or a second code path
would each leave authorship behind and none would error. Nothing on the live stream carries a member,
and nothing on it carries a timing a member could read: a preference write returns 204 and emits no
event, because at five people the moment of an event is one guess away from a name. Preferences are
per meal unless kept, erased nightly by a job whose role can read and delete that table and nothing
else; weather readings older than ninety days go the same way unless a roll pinned them.

## Quick start

```sh
cp .env.example .env      # names only — the comments state the shape of every value
docker compose up -d --wait
curl -s localhost:8080/health   # {"status":"ok","database":"reachable"}
```

- **`localhost:8080`** — the app (`UPTO_HTTP_PORT`); the API and the database are reachable only
  over the compose network. `UPTO_HTTPS_PORT` defaults to 8443 and serves nothing until a `tls/`
  snippet exists — a fresh clone needs no privileged port and no certificate.
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

62 test files. Fetch, hash and parse are unit-tested with no network and no
database, which is what keeps the DAGs thin — they supply only *when* and *with which database*:

```sh
python3 api/tests/test_cwa_ingest.py    # and test_fda_ingest, test_fia_ingest, test_dice_table,
python3 api/tests/test_weight_fold.py   # test_classify, test_web_surface, test_evaluate_draw …
```

Integration tests build and drop their own database, in the test-only service that holds the
owner's credential — never in `api`, which connects as a role that cannot `create database`. Every
source is proven idempotent through its real CLI twice, every column compared:

```sh
docker compose run --rm tests python /srv/tests/test_place_ingest_integration.py
docker compose run --rm tests python /srv/tests/test_business_tax_integration.py
```

## Scope

Taipei only — twelve townships, one city's open data, addresses normalised at the ingest boundary
because the same government file spells the city two ways. Every source is used inside its licence,
and a source whose licence is non-commercial or uncertain is not used at all; there are no ratings,
no reviews and no scraped pages anywhere in the pipeline. Sized for one small group: one API
worker, live room state in memory, five friends rather than five thousand. A portfolio project,
developed in a private repository and extracted here after every merge, so the commit messages
carry the reasoning behind each change.
