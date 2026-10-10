# Up to you

[English](README.md) | [繁體中文](README.zh-TW.md)

**When friends can't agree where to eat, a pair of weighted dice makes the call, so nobody has to.**

*You said «anywhere is fine». Did you mean it, or did you just not want to be the one who picked?*

**Try it: [uptoyou.jacksong-tw.com](https://uptoyou.jacksong-tw.com)**

## Why this exists

A few friends want dinner. Everybody has a mild preference. Twenty minutes later nobody has chosen,
or the loudest voice did.

Choosing where a group eats goes wrong in three familiar ways:

1. **Nobody wants to own the choice.** Whoever picks carries «we should never have come here», so
   everyone says «anywhere is fine» and the decision stalls.
2. **The usual fixes move the argument instead of ending it.** A ranking makes the group argue about
   the ranking, and someone still has to pick from it. A vote settles it by majority, so the same
   person loses every time.
3. **What the group knows gets lost.** It is raining over one district, you ate at one place last
   week, someone cannot eat a whole kind of food tonight. A coin toss ignores all of it; a debate
   lets whoever speaks loudest decide which facts count.

Up to you hands the choice to a draw nobody owns, and lets those facts change each place's chances in
the open:

- every proposed place can be drawn, and what the group knows lowers its chances by written rules,
  never by someone's say-so;
- the draw is fixed before anyone proposes, so nobody can steer it;
- what each person would rather skip tonight stays theirs: it moves the chances and is never shown
  to the others;
- it never says a place is good, only facts about it.

## How the dice decide

Two dice have 36 outcomes, one per drawer of the 籤詩櫃 (a temple's cabinet of fortune slips). Each proposed place holds some of them, and the group's facts change how
many:

| Factor | Effect on a place's odds | Why |
|---|---|---|
| Rain over its district | lowered, relative to the driest district in tonight's pool | walking in the rain is a real cost |
| The circle went there last time | halved | variety, without removing the option |
| Someone avoids its category | lowered by 1/N, N = seats at the table | one objection among five weighs less than among two |
| Nothing applies | unchanged | every place starts at 1 |

These are **weighted dice, not a ranking**. An avoided category is **a discount, not a veto**: with five
at the table it loses a fifth and stays reachable. The constants are written policy (×0.5, 1/N, ×0.8);
with no record of what real groups chose, there is nothing to train a scorer on, and a stated rule can
be checked.

## How to use it

> **Try this in 30 seconds.** Open the site and create a circle (a group deciding one meal). Copy the invite link and open it in a
> private window: that is your second friend. Each of you proposes a place and presses 提交 (submit); when everyone is in, the reveal opens.
>
> *What the live demo holds:* Taipei's restaurants only, on one small server sized for a few groups at
> once. No account, no email.

1. **Open the home page**: today's weather, and 開一個圈子 to start.

   ![The home page](docs/tutorial/0-home.png)

2. **Create a circle**: name the group and yourself.

   ![Create a circle](docs/tutorial/1-create.png)

3. **Send the invite link** (the link itself is hidden in this picture; it opens a seat for whoever taps it).

   ![The invite panel](docs/tutorial/2-invite.png)

4. **A friend joins** with a nickname.

   ![A friend joins](docs/tutorial/3-join.png)

5. **Propose places, and tick 這次不想吃的類別** (the categories you'd skip tonight; your own, never shown to others).

   ![Proposing places](docs/tutorial/4-propose.png)

6. **Press 提交** (submit); the round lists 還沒提交 (not yet) and 已提交 (submitted) until everyone is in.

   ![Waiting for everyone](docs/tutorial/5-waiting.png)

7. **The reveal**: dice or the 籤筒, picked per round, then the drawer and its fortune slip.

   ![The reveal](docs/tutorial/6-reveal.png)

---

*Everything below is how it's built.*

[![ci](https://github.com/JacksonG-TW/Uptoyou/actions/workflows/ci.yml/badge.svg)](https://github.com/JacksonG-TW/Uptoyou/actions/workflows/ci.yml) [![frontend](https://img.shields.io/badge/frontend-React%2019%20%2B%20Vite-61DAFB?logo=react&logoColor=black)](https://react.dev/) [![backend](https://img.shields.io/badge/backend-FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/) [![db](https://img.shields.io/badge/db-PostgreSQL%2017-4169E1?logo=postgresql&logoColor=white)](https://www.postgresql.org/) [![vector](https://img.shields.io/badge/vector-pgvector-4169E1?logo=postgresql&logoColor=white)](https://github.com/pgvector/pgvector) [![orchestration](https://img.shields.io/badge/orchestration-Airflow-017CEE?logo=apacheairflow&logoColor=white)](https://airflow.apache.org/) [![AI](https://img.shields.io/badge/AI-gemma2%20(2B)%20%2B%20arctic--embed2-000000?logo=ollama&logoColor=white)](https://ollama.com/) [![deploy](https://img.shields.io/badge/deploy-EC2%20%2B%20Cloudflare-FF9900?logo=amazonaws&logoColor=white)](#system-architecture)

**Where to read next:** [The data pipeline →](#the-data-pipeline) ·
[The classifier →](#the-classifier-and-its-evaluation) ·
[The draw and privacy →](#the-draw-and-privacy-in-the-database) · [Run it yourself →](#quick-start)

## The work, in three numbers

| | Before → after | What was measured |
|---|---|---|
| **Data pipeline** | A night with no new data: **15.0 s → 1.6 s** | Seven government sources (six scheduled jobs: one weather job feeds two of them) refresh 35,965 Taipei restaurants every night. An unchanged file is recognised by the hash of its bytes and never re-read. |
| **AI classification** | Cuisine labels: **51.5% → 61.0% correct** by adding retrieval | A local 2-billion-parameter model labels each restaurant, scored on 200 frozen hand-labelled names. Retrieving five labelled look-alikes first gave the jump. The set was later re-cut to thirteen categories with 19 rows relabelled; there it reads 71.0% (a different set, so the two are not compared). An [MCP tool](#a-tool-for-ai-agents-lineage-over-mcp) lets an AI agent ask where any number came from (which government file, which nightly run) without writing SQL. |
| **Production** | The API's live link to the database is cut: `/health` reports it in **0.18 s**, reconnects in **1.23 s** | Live on one EC2 behind Cloudflare. A failed nightly job sends a phone alert; the nightly backup restores into a fresh database in 9.4 s. |

## The data pipeline

### Seven sources, one schedule

![The ETL pipeline: seven sources into one store with a run log](docs/diagrams/etl-flow.png)

Seven sources in six ingest jobs: the CWA weather job brings in both the forecast and the station observations. Every source is published open data, used inside its licence. Sources are joined on the registry
numbers they share (統編, 登錄字號), never on fuzzy name matching.

| Taipei time | Job | What it brings in |
|---|---|---|
| hourly | CWA weather | township forecast `F-D0047-061` + station observations `O-A0001-001` |
| 03:00 | 食藥署 食品業者登錄 | the restaurant reference list |
| 03:20 | 臺北市食材登錄平台 | company ↔ brand pairs |
| 03:40 | 臺北市餐飲衛生分級評核 | the shop sign an inspector saw |
| 04:00 | 商業登記-餐館業 | which registrations are dead |
| 04:20 | 財政部 全國營業(稅籍)登記 | tax name + industry code |
| 04:30 | freshness check | names any source that stopped publishing, and for how many hours |
| 05:00 | preference erasure | deletes per-meal preferences no roll used |
| 05:40 | weather retention | deletes readings older than ninety days no roll used |
| 06:00 | circle sweep | removes abandoned circles |
| 06:20 | backup | `pg_dump` to S3, after both deletions; the last thirty kept |
| 07:00 | dataset export | a Parquet file of every place, to S3 beside the dump |

The daily sources start twenty minutes apart so two never compete for the server's memory, and the
deletions run before the backup so a dump never carries a row the product has already forgotten.

### When something goes wrong

- **A failed task retries twice, ten minutes apart, then sends one Telegram message** with the task's
  name in plain words and the log's path. A job that fails on purpose tests the alert channel itself,
  because «no alert» and «alerting is broken» look the same from outside.
- **Two data-quality checks run after each ingest.** The publication check compares a new file's
  columns with the last one's and names any that appeared or vanished, and flags a row count that
  dropped 20% or more. The value check records hours since the last publication, recent failures and
  the row-count step, and alerts with the source's name and the hours when one goes stale.
- **Every attempt writes a row to the run log**, so «nothing changed» and «failed» are two recorded
  outcomes. Without that, a broken source looks healthy for a week.
- **The nightly backup is drilled.** A 19.7 MB dump finishes in 3.7 s and restores into a fresh
  database in 9.4 s, with every row count equal.

### Content-addressed ingest

**A fetched file is identified by the hash of its bytes, not a timestamp**, the way git names a
commit. A timestamp can change while the data stays the same. The reference ingest hashes a 17 MB zip
and claims that hash with `insert … on conflict do nothing returning id`: an id comes back and the
99 MB CSV inside is decompressed, or nothing comes back and the run stops there.

The conflict *is* the answer: the content is unchanged, so the parse is skipped. That is the 15.0 s →
1.6 s above. The claim is one statement, so two runs starting together cannot both decide the file is
new.

Measured on the schedule itself, 8 days, 332 run-log rows:

| Source | New file stored (median) | Nothing new (median) |
|---|---|---|
| CWA township forecast | 2.99 s | 1.85 s |
| CWA station observation | 3.09 s | 0.31 s |
| 食材登錄 brands | 0.57 s | 0.96 s |
| 衛生評核 signs | 0.31 s | 0.43 s |
| 商業登記 status | 25.03 s | 2.09 s |
| 營業稅籍 registry | 12.95 s | 3.58 s |

A night with nothing new saves 3.6× on the tax registry and 12× on the business registration.
Airflow's own overhead is flat, about 1.2 s a task.

### Names: one restaurant, three names

The government list says 安心食品服務股份有限公司. You know it as 摩斯漢堡. 40.2% of registered names
are company names that name no shop. So a display name is resolved down a ladder: the sign an
inspector recorded, then the brand, then the registered name, joined by registry number with fixed
precedence.

![The name ladder: sign, then brand, then registered name](docs/diagrams/name-ladder.png)

| Step | Rows | Share |
|---|---|---|
| sign | 1,363 | 3.7% |
| brand (single-brand companies) | 4,003 | 11.0% |
| registered name (the rest) | 31,010 | 85.2% |

Overture Maps, the open global places dataset, was tried and dropped: 39.5% trustworthy matches and
46% false joins on address alone.

### Data model

![The schema at a glance](docs/diagrams/schema-glance.png)

The production database is **490 MB**: 35,965 places, 25,031 with a generated category. Source tables keep every publication side by side, so a new file adds a full set of rows and never overwrites the last one.

| Table | Rows | What it holds |
|---|---|---|
| `place` | 35,965 | a place a circle can choose |
| `reference_place` | 72,963 | the government reference list, two publications (36,376 and 36,587 rows) |
| `storefront_name` | 1,686 | the sign an inspector recorded |
| `brand_registration` | 288 | company ↔ brand pairs |
| `business_tax_row` | 363,412 | tax-registry name and industry code |
| `business_status_row` | 419,896 | business-registration status |
| `forecast_reading` | 970,190 | township forecast readings |
| `observation_reading` | 136,800 | station observation readings |
| `ingest_run` | 1,766 | one row per ingest attempt, including «no change» |

Every weight the dice use is a stored row linked to the reading it came from, and a lineage tool
answers «where did this number come from» for an AI agent ([below](#a-tool-for-ai-agents-lineage-over-mcp)).

## The classifier and its evaluation

### What the model does

No published source says what a restaurant serves. So a local model reads the best name the pipeline
holds and picks one of thirteen cuisine categories (麵食, 火鍋, 日式, 咖啡飲料, …). An answer outside the
thirteen is refused.

It is RAG in three steps:

- **Retrieval:** pgvector finds the five most similar names that already have a label.
- **Augmented:** they go into the prompt as worked examples, beside the name to classify.
- **Generation:** `gemma2:2b` answers with one category.

Missing knowledge is added as labelled examples; the prompt and the model's weights stay as they are.

### How it is scored

**One frozen set of 200 names**, drawn once in proportion to the categories, labelled by hand, and
never re-drawn between rounds. The metric is **accuracy**: the share of names where the model's
category equals the hand label. Every candidate runs once on the same set, through the same pipeline
the nightly job uses.

| Model | Licence | Accuracy on the 200 |
|---|---|---|
| `qwen2.5:7b-instruct` | Apache-2.0 | **72.0%** |
| `gemma2:2b` (in use) | Gemma terms | 71.0% |
| `llama3.2:3b` | Llama 3.2 community | 70.5% |
| `qwen2.5:3b-instruct` | research licence, evaluation only | 65.5% |

**Why the 2B model:** the top three sit within two points, and the 7B costs three times as much per
name. The set also caught a prompt revision that read better and scored worse (51.5 → 49.5).

**Retrieval is measured per model**, because the same examples help one model and confuse another: on
the earlier set retrieval moved `gemma2:2b` 51.5 → 61.0 and `llama3.2:3b` 37.0 → 58.0, while
`qwen2.5:3b` went 51.0 → 48.5.

![The evaluation loop: how a classifier candidate is scored](docs/diagrams/evaluation-flow.png)

The embedder was screened the same way (nearest neighbour's label as the answer, leave-one-out):

| Embedder | Accuracy |
|---|---|
| `snowflake-arctic-embed2`, bare (in use) | **55.0%** |
| `snowflake-arctic-embed2`, with its `query:` prefix | 53.5% |
| `e5`, with `query:` | 51.5% |
| `0.6b`, with an instruction | 51.5% |

### Why local

- **Quota:** a hosted model's free tier allows 500 calls a day, so 3,300 places take a week; the
  local run takes one night.
- **Data:** the names never leave the machine.
- **Latency does not matter:** classification is a nightly batch nobody waits for.

The whole city, **36,014 names in 10.5 hours** on one 8 GB graphics card (0.92 s a name; the same
box's CPU takes 12–19 s). The production server runs no model.

### Where the official codes help

The tax registry carries an industry code. A coffee chain's 245 branches register under a wholesale
code, so codes alone would mislabel all of them. The codes decide where they are unambiguous (10.9% of
the city) and the model takes the rest.

### A tool for AI agents: lineage over MCP

An MCP server over stdio lets an agent ask where a number came from without writing SQL. Six tools
answer: where a forecast reading was published, where an observation came from, which rows each factor
of a roll read, what one ingest attempt did, a source's history, one publication's detail. It connects
as its own database role with read access to twelve tables. A seventh tool, `explain_place_loss`,
exists only to refuse: why a place lost runs through members' private preferences, so the boundary is
listed where an agent can see it.

## The draw and privacy, in the database

**The draw is fixed before the first proposal**: a seed is committed when the round opens and revealed
when it closes, and both travel with the result, so anyone in the circle can check the draw against what
was fixed at the start. Every factor is written as a row when the round closes; the operator's receipt
reads those rows back and recomputes nothing.

**Privacy is enforced in the database.** Closing a round fires a trigger that removes who proposed
what, in the same transaction that saves the result. A preference write emits no event at all, because
in a small group the moment of an event is one guess away from a name. A nightly job erases unused
preferences under a role that can touch that one table and nothing else.

## System architecture

![Architecture: the stack as it is served](docs/diagrams/architecture.png)

**One small EC2, one compose file, one PostgreSQL** doing both the relational queries and the vector
search, so there is no second service to run and back up for the vectors.

| Layer | What runs |
|---|---|
| **Front end** | Vite + React 19 + Tailwind 4 + shadcn/ui, built inside the proxy image. No CDN and no runtime fetch; two fonts cut down to the characters the pages use. |
| **API** | Python, FastAPI, SQLAlchemy, async end to end; 50 hand-written Alembic migrations (triggers, grants and CHECK constraints). |
| **Database** | PostgreSQL 17 with pgvector. Seven login roles, one per job: the API, the ingests, the erasure, the backup, the lineage tool, the value checks, and the owner, held only by the one-shot migration container. |
| **Orchestration** | Apache Airflow 3, LocalExecutor, in the same compose stack. |
| **Models** | Ollama on an 8 GB card at home, used in nightly batches; production runs no model. |
| **Deployment** | EC2 in Tokyo behind Cloudflare (Full strict). The server pulls published images and builds nothing; nothing pushes into it. An API process that finds the database at the wrong schema version exits at startup instead of serving. |

### Tests and CI

The CI badge above runs on every public commit: **the tests that need no database** (standard
library only), **the web build with its type check and lint**, and **the compose file read as a fresh
clone would**. The full suite is 76 test files in two tempos: host-side tests with no network, and
tests that build and drop their own database. Seven local checks run before every commit (secrets,
what may leave app/, fonts, the server's user-facing text and status table, staged Python).

## Performance

| What | Before | After | Measured on |
|---|---|---|---|
| A night with no new file (reference source) | 15.0 s | **1.6 s** | the run log, 8 days |
| Embedding one name | 0.481 s | **0.045 s** | 100 names, twice |
| Classifying one name | 12–19 s on CPU | **0.92 s** on an 8 GB card | one district, 1,318 names |
| The registry roster ingest's peak memory | 172 MB | **77 MB** | a 2 GB server |
| The serving stack at rest | 1,131 MiB | **1,009 MiB** | a 2 GB server |
| A long classification pass, first vs last hour | 1.7× slower | **level** | 36,014 names in 10.5 h |

**Name search has no index; it scans.** A trigram index was tried across 31 real queries and the
database never used it. The slow part was a sub-query that ran once per candidate row, 35,533 times
per keystroke. Measure first, then decide whether to index.

[The long version](docs/decisions.md) has the working behind every number.

## Limits and future work

**Taipei only**, twelve districts and one city's open data. **Sized for a few groups at once.** Every
source is used inside its licence; there are no ratings, reviews or scraped pages anywhere.

- **素食 becomes an attribute** a place carries (素食麵館 = 麵食 + 有素), since «I cannot eat here» is a
  hard requirement and a discount does not fit it.
- **More than one API instance behind a load balancer**: the event bus already lives in the database.
- **MLflow over the evaluation rounds**, replacing the round files' bookkeeping.
- **«Did you actually go?» from a transaction** (a POS or loyalty partner) would beat asking the group,
  but data like that moves under a commercial agreement and Taiwan's PDPA; none is approached.

## Quick start

```sh
cp .env.example .env                # names only; the comments state the shape of every value
docker compose run --rm migrate     # the schema, once per version
docker compose up -d --wait         # the stack
curl -s localhost:8080/health
#   {"status":"ok","database":"reachable","instance":"…","stream_listener":"up"}
```

**A fresh clone comes up empty, then fills itself.** Places arrive with the first reference ingest
(overnight, or [by hand](docs/operations.md)). Categories need the classifier backfill, which needs a
graphics card; without one you get every place with the category column empty.

`localhost:8080` is the app. The weather ingest needs a free CWA Open Data key
(opendata.cwa.gov.tw); the five open-data files need no credential. New scheduled jobs arrive paused.

Running an ingest by hand, a backfill, the tests and the lineage tool:
[docs/operations.md](docs/operations.md).
