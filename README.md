# Up to you

[English](README.md) | [繁體中文](README.zh-TW.md)

[![frontend](https://img.shields.io/badge/frontend-React%2019%20%2B%20Vite-61DAFB?logo=react&logoColor=black)](https://react.dev/) [![backend](https://img.shields.io/badge/backend-FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/) [![db](https://img.shields.io/badge/db-PostgreSQL%2017-4169E1?logo=postgresql&logoColor=white)](https://www.postgresql.org/) [![vector](https://img.shields.io/badge/vector-pgvector-4169E1?logo=postgresql&logoColor=white)](https://github.com/pgvector/pgvector) [![orchestration](https://img.shields.io/badge/orchestration-Airflow-017CEE?logo=apacheairflow&logoColor=white)](https://airflow.apache.org/) [![AI](https://img.shields.io/badge/AI-gemma2%3A2b%20%2B%20arctic--embed2-000000?logo=ollama&logoColor=white)](https://ollama.com/) [![data](https://img.shields.io/badge/data-35%2C965%20places-555555)](#data) [![deploy](https://img.shields.io/badge/deploy-EC2%20%2B%20Cloudflare-FF9900?logo=amazonaws&logoColor=white)](#architecture)

**A group decides one meal together, and a weighted pair of dice does the choosing.**

For a small group who can never agree where to eat — and who would rather see why a place won than
be told to trust a ranking.

**Try it: [uptoyou.jacksong-tw.com](https://uptoyou.jacksong-tw.com)**

### Try this round

```sh
docker compose run --rm migrate                          # the schema, once per version
docker compose up -d --wait                              # the stack
docker compose exec api python -m upto.issue 1 Kevin     # a device token, printed once
```

Open `localhost:8080`, paste the token, propose three places, roll.

| | |
|---|---|
| **The idea** | A few friends, one meal, nobody wants to be the one who chose. The app chooses, and then shows its work. |
| **How it decides** | Weighted dice, not a ranking. Every factor multiplies a place's odds, and the reveal names each factor beside the number it contributed. |
| **Data** | Seven published government sources through six scheduled ingests; 35,965 Taipei places, 25,031 of them carrying a generated category. |
| **Engineering** | Content-addressed ingest with an idempotent ledger, a three-rung name derivation, and a retrieval-augmented classifier scored on a frozen set. |
| **Measured** | Four local models on one frozen set: 72.0 · 71.0 · 70.5 · 65.5. A no-change ingest costs 1.6 s against 15.0 s to store. The whole city classified in 10.5 h. |
| **Why this stack** | One compose file, one database doing both relational and vector work, and no service that cannot run on a small cloud instance. |

*This English page is canonical: where the two languages disagree, this one is right.*

## See it work

![A round from start to finish — propose, roll, reveal](docs/reveal-walk.webp)

Five screens, and each does one thing:

- **Home** — the circle, and tonight's round if one is open.
- **Device** — paste a token once; the browser remembers the circle.
- **Tonight (這一餐)** — the categories to avoid tonight, as a menu with section marks.
- **Round** — propose places, then roll.
- **Reveal** — the dice stop, then the winner's odds are itemised, factor by factor.

## Why this exists

### The problem

A few friends want dinner. Everybody has a mild preference and nobody wants to own the decision, so
the group either defaults to the loudest voice or spends twenty minutes not choosing.

The usual software answer is a ranking. That only moves the argument: now the group argues about
whether the ranking is right, and whoever picks from it still owns the choice.

### Why dice, and why weighted

Dice are fair by construction. Nobody picked, so nobody has to defend the pick — and that is the
social problem, answered by the mechanism rather than by persuasion.

But plain dice ignore everything the group knows. So the dice are weighted: each place gets a share
of the thirty-six outcomes, and the things that matter move that share. A category somebody avoids
is a **discount, not a veto** — proportional to how many people are at the table. With N at the
table one objection costs a place 1/N of its odds, so at N = 5 it loses a fifth and stays reachable;
at N = 1 it is a veto, because a round of one person is that person's decision.

<!-- Picture belongs here: docs/reveal-panel.png -->

### Why show the work

A weighted die is only trustworthy if you can see the weights. Every factor is a stored row, pinned
to the reading it was computed from, and the reveal recomputes nothing for display — it reads the
same rows the roll used and names each one.

That is the difference between a result you are asked to trust and one you can check. It is also why
a preference is private on the way in and visible on the way out: what moved the odds is shown, who
asked for it is not.

<!-- Picture belongs here: docs/round-tonight.png -->

### Why the data is the hard part

Deciding is easy once you know the choices. Knowing the choices is the work.

**A registered name is a legal entity, not a shop.** The government's restaurant list knows
安心食品服務股份有限公司. The people deciding where to eat know 摩斯漢堡. Those are the same company and
only one of them is a name anybody would recognise, so a display name is resolved down a ladder — the
sign an inspector recorded, then the brand, then the registered name.

**And no published source says what a place serves.** There is no official field for «this is a
noodle shop». So the category is generated: a local model reads the best name the project holds and
answers from a closed list of thirteen, and its accuracy is measured on a frozen set rather than
asserted.

<!-- Picture belongs here: docs/diagrams/name-ladder.png -->

## How it decides

Each factor multiplies a place's share of the thirty-six outcomes. They are stored, not computed at
display time.

| Factor | What it does to a place's odds | Why |
|---|---|---|
| Rain over its district | Lowers them, relative to the driest district in tonight's pool | Walking somewhere in the rain is a real cost, and it is a fact about tonight rather than about the place |
| The circle went there last week | Halves them | Variety, without removing the option — only a signed trip counts, so a place the group merely rolled is untouched |
| Somebody avoided its category | Lowers them by 1/N, where N is the seats at the table | A discount, not a veto: one objection among five is not the same as one among two |
| Nothing applies | Leaves them alone | The starting weight is 1, and a factor that did not fire draws an empty row rather than vanishing |

## Highlights

- **35,965 places** from seven published government sources, each fetch content-addressed so an
  unchanged file costs nothing.
- **A classifier scored on a frozen 200-row set**, four local models compared on it: 72.0 · 71.0 ·
  70.5 · 65.5.
- **Every factor a stored row** a member can read on the reveal, pinned to the reading it came from.

## Terminology

| Term | What it means here |
|---|---|
| **Circle** | A standing group of people who eat together. |
| **Member** | One person's seat in a circle. No account, no email — a device token. |
| **Round** | One meal being decided. It opens, collects proposals, and closes on a roll. |
| **Proposal** | A place somebody put forward in this round. |
| **Roll** | Two dice, weighted by the round's factors. One roll counts, named before the dice are seen. |
| **Reveal** | The screen after the roll: the winner, and every factor that moved its odds. |
| **Contribution** | One stored factor — what it multiplied by, which contributor produced it, and which reading it came from. |
| **Place** | A restaurant. Either a row from the published reference list, or one a circle added itself. |
| **Publication** | One fetched file, identified by the hash of its bytes. Never overwritten. |
| **Ingest run** | One attempt at one source. Records what happened, including «nothing had changed». |
| **Name ladder** | How a display name is chosen: storefront sign, then brand, then registered name. |
| **Category** | One of thirteen closed values a place can be classified into. |
| **Crib** | The labeled examples retrieved from the vector store and handed to the classifier as worked examples. |

## Architecture

![Architecture — the stack as it is served](docs/diagrams/architecture.png)

*One host, one compose file. Cloudflare terminates TLS at the edge and the origin answers with its
own certificate; the four Airflow services and the API share one PostgreSQL, each connecting as
its own role.*

| Layer | What runs |
|---|---|
| **Front end** | Vite + React 19 + Tailwind 4 + shadcn/ui, built inside the proxy image. No CDN, no runtime fetch; two subset fonts ship with the bundle. |
| **API** | Python, FastAPI, SQLAlchemy 2.0, async end to end, 43 hand-written Alembic migrations. |
| **Database** | PostgreSQL 17. Five login roles, one per boundary: the API, the ingests, the nightly erasure, the backup, and the owner — which only the one-shot migration container ever holds. |
| **Vector** | pgvector, in that same database. |
| **Orchestration** | Apache Airflow 3, LocalExecutor, in the same compose stack. Its metadata is a second database in the same PostgreSQL. |
| **Models** | Ollama on a home box's 8 GB card, reached through a relay. `gemma2:2b` generates, `snowflake-arctic-embed2` retrieves. |
| **Deployment** | One EC2 instance in Tokyo behind Cloudflare in Full (strict). It pulls images from a public registry and builds nothing. |

## Data

![The ETL pipeline — seven sources into one ledgered store](docs/diagrams/etl-flow.png)

| Schedule (UTC) | Taipei | Source |
|---|---|---|
| hourly | hourly | CWA township forecast `F-D0047-061` + station observations `O-A0001-001` |
| `0 19 * * *` | 03:00 | 食藥署 食品業者登錄 — the restaurant reference list |
| `20 19 * * *` | 03:20 | 臺北市食材登錄平台 — company ↔ brand pairs |
| `40 19 * * *` | 03:40 | 臺北市餐飲衛生分級評核 — the sign an inspector saw |
| `0 20 * * *` | 04:00 | 商業登記-餐館業 — which registrations are dead |
| `20 20 * * *` | 04:20 | 財政部 全國營業(稅籍)登記 — tax name + industry code |
| `0 21 * * *` | 05:00 | deletes every per-meal preference row a roll did not pin |
| `40 21 * * *` | 05:40 | deletes unpinned weather readings older than ninety days |
| `20 22 * * *` | 06:20 | `pg_dump` to S3 after both deletions, thirty kept |

**A publication is identified by the hash of its bytes, not by a timestamp**, because a stamp can
move while the data stands still and stand still while the data moves. The reference ingest hashes a
17 MB zip and claims the publication with `insert … on conflict do nothing returning id` — the
database decides whether the content is new — and only then does anything decompress the 99 MB CSV
inside. Every attempt writes a ledger row, and «no change» and «failed» are different recorded
outcomes: inferred from an absence they are indistinguishable, which is how a broken source looks
healthy for a week.

**How far the name ladder reaches**, over the current publication's 36,499 rows — a count of
published rows, not the 35,965 places the serving instance holds:

| Rung | Rows | Share | Of those, still names a company |
|---|---|---|---|
| sign (site-level) | 1,379 | 3.8% | 3.3% |
| brand (single-brand companies only) | 4,001 | 11.0% | 44.0% |
| registered (what is left) | 31,119 | 85.3% | 33.3% |

The ladder reaches 14.7% of the city, and 33.3% of all rows still display a string that names a
company rather than a shop. Where a sign exists the name is right, and a sign exists for one row in
twenty-six.

[The long version](docs/decisions.md) has what each source stores, the thirteen categories and how an
answer outside them is refused, and how the frozen evaluation set was drawn.

## Key technical decisions

Five choices, each with what was turned down and the number that decided it.

![The evaluation loop — how a classifier candidate is scored](docs/diagrams/evaluation-flow.png)

*The same 200 frozen rows, one round per model, scored and never re-run.*

**1. Classification runs on a local 3B model; the cloud model is a yardstick, not a worker.**
*Chosen:* a quantized 3B generator on the same box as the database, batch-only, off unless a
backfill runs. *Turned down:* a hosted model as the classifier. *The number:* the free hosted tier
allows 500 calls a day, so 3,300 places take seven days; the local model does them in one night —
and the hosted model's score is kept, as the line the local ones are measured against.

**2. Missing knowledge is added as data, not as prompt text or weights.**
*Chosen:* a retrieval crib — labeled example names embedded into pgvector, the five nearest handed
to the model as worked examples. *Turned down:* another prompt revision; fine-tuning. *The number:*
the prompt revision *lost* points on the frozen set (51.5 → 49.5); retrieval on the same set moved
`gemma2:2b` 51.5 → 61.0 and `llama3.2:3b` 37.0 → 58.0, while `qwen2.5:3b` went 51.0 → 48.5 — the
same crib reads as noise to one model, which is why the pairing is measured rather than assumed.

*The current table* — prompt v7, thirteen categories, `testset_v3`, the same crib
(`snowflake-arctic-embed2`, five neighbours), every round on the home box through the same relay the
scheduled pass uses:

| model | licence | pooled accuracy (200 rows) |
|---|---|---|
| `qwen2.5:7b-instruct` | Apache-2.0 | **72.0%** |
| `gemma2:2b` | Gemma terms | 71.0% |
| `llama3.2:3b` | Llama 3.2 community | 70.5% |
| `qwen2.5:3b-instruct` | research licence — evaluation only | 65.5% |

Three models inside two points of each other, one of them three times the cost per row; the
scheduled pass kept `gemma2:2b`. The hosted yardstick read 60.5% on the first set only.

**3. A shop's name is resolved down a ladder — sign, then brand, then registered name.**
*Chosen:* three sources joined by registry number, precedence fixed, no fuzzy name matching.
*Turned down:* the registered name alone; string similarity across sources. *The number:* 40.2% of
registered names are legal-entity strings that name no shop at all; the sign differs from the
registered name on 93% of the rows that have one; the brand table renames 57% of the companies it
covers; and a trial of an outside geodata source false-joined 46% on address alone and was dropped.

**4. Official industry codes decide only what they can, and that is one row in ten.**
*Chosen:* the tax registry's codes rule where unambiguous, the model takes the rest. *Turned down:*
codes as the classifier; ignoring codes entirely. *The number:* codes settle 10.9% of city rows, and
a coffee chain's 245 branches register under a wholesale code — a code alone would mislabel every
one of them. The join itself is safe (99.78% name agreement once the legal-form suffix is stripped);
the address is not (89.8% differ). [The long version](docs/decisions.md) measures the same question
on the 200 scored rows, where the defensible upside is +4 rows.

**5. Every source is content-addressed and its no-change days are recorded.**
*Chosen:* a publication row per fetched file, a data row per record, and a ledger where a no-change
day writes a heartbeat. *Turned down:* overwrite-in-place; schedules guessed to match each file's
cadence. *The number:* every source is idempotent on identical bytes — every column of every table
compared, through the real command-line entry point, twice — and on the reference source the
no-change path costs 1.6 s against 15.0 s to store. Per-source figures are in the table below and
they spread much wider than that one pair.

*Measured on the schedule itself* — 8 days, 332 ledger rows against 361 Airflow task instances,
nothing instrumented and no column added:

| Source | Store p50 | No-change p50 | Ledger rows |
|---|---|---|---|
| CWA township forecast | 2.99 s | 1.85 s | 149 |
| CWA station observation | 3.09 s | 0.31 s (n=1) | 149 |
| FDA 餐飲場所 reference | none yet | 1.88 s | 5 |
| 食材登錄 brands | 0.57 s | 0.96 s | 8 |
| 衛生評核 signs | 0.31 s | 0.43 s | 7 |
| 商業登記 status | 25.03 s | 2.09 s | 7 |
| 營業稅籍 registry | 12.95 s | 3.58 s | 7 |

**The no-change day is 3.6× cheaper than a store on the largest source** and 12× on the registry
roster — the claim-before-parse short-circuit, priced. **Orchestration costs a flat 1.2 s a task**,
the same whether the source takes half a second or twenty-five. **The scheduler is not the
bottleneck:** queue latency is 0.05 s at p50 and 4.2 s at its worst across all 361 tasks. What none
of this answers is the fetch / parse / store split — nothing records it.

### Six more, with their numbers

- **Vector search is a Postgres extension, not a second service.** The crib is 537 rows across three
  embedders, against one more stateful service to run, back up and monitor.
- **The evaluation set is frozen, stratified, and its authorship is stated.** It caught a prompt that
  read better and scored worse, which is the only thing a fixed set exists to do.
- **Substring search stays a sequential scan.** A trigram index changed the plan for 0 of 31
  realistic queries; the cost was a lateral executed 35,533 times per keystroke, not the scan.
- **The small instance was too small for its own nightly work.** 49 MB free under one ingest became
  398 MB worst case, and the stack went 1,131 → 1,009 MiB at rest.
- **The cloud serves; the home box computes.** An 8 GB card takes a retrieval-shaped batch at 0.92 s
  a name, against 12–19 s on the same box's CPU.
- **The live stream sends a heartbeat**, because through the proxy a stream silent for 130 s was cut
  and a real event afterwards delivered nothing.

[The long version](docs/decisions.md) has each of these in full.

## What changed, measured

Six numbers where a change was made and both sides were measured.

| What | Before | After | Measured on |
|---|---|---|---|
| An ingest day with no new file | 15.0 s | **1.6 s** | the run ledger, 8 days, 7 sources |
| Embedding one name for the crib | 0.481 s | **0.045 s** | 100 names, twice, 09-04 |
| Classifying one name | 12–19 s on the CPU | **1.27 → 0.92 s** on an 8 GB card | one district, 1,318 rows |
| The registry roster ingest's peak memory | 172 MB | **77 MB** | a 2 GB instance, 09-05 |
| The serving stack at rest | 1,131 MiB | **1,009 MiB** | a 2 GB instance, 09-07 |
| A long classification pass | 1.7× slower first-to-last | **level** | 36,014 rows in 10.5 h, 09-03 |

The memory figures were measured on the 2 GB instance they were taken on; the instance has since
been resized. [The long version](docs/decisions.md) has the working for the last four.

## Observability and reliability

- **The stream's heartbeat is a comment line every 25 s**, because a silence longer than 130 s is
  cut by the proxy in front of it. It carries no timing a member could read.
- **Each API process holds one listening connection to the database** and fans events out from it,
  so more than one instance can serve one circle. If that connection dies the process says so:
  `/health` answers 503 with `stream_listener` and the time it went down, while still serving reads.
  Measured on a real kill: **503 within 0.18 s, back up on a new connection within 1.23 s.**
- **An API process refuses to serve a schema it was not written against.** It reads the migration
  revision at startup and, if the database is behind, ahead, or never migrated, logs both revisions
  and exits — so a deploy fails at the container that is wrong rather than inside a member's request.
- **The model link is retried, and the retry count is printed.** A cold model on that path presents
  as *down* rather than as slow: the first request fails and the retry twelve seconds later answers
  in half a second. A flaky link reads as a number rather than as a slow night.
- **A failed scheduled task sends one message**, carrying the log's path inside the container and
  never a URL. Alerting is off in a fresh clone by design, and a dedicated job exists that fails on
  purpose so the channel itself can be tested.

## Development journey

| Dates | Phase | What changed | The number |
|---|---|---|---|
| 08-11 to 08-17 | Skeleton and the architecture walk | The stack boots from one compose file; the destination, the batch classifier and its stop-loss ladder settled one at a time; first evaluation rounds on a fixed set | prompts v3 → v5 in two days; v5 with retrieval scored **66.0%** on a 200-row set drawn once |
| 08-18 | The surface reversed | The hand-rolled, no-build front end is replaced by Vite + React 19 + Tailwind 4 + shadcn/ui, built inside the proxy image | one night to re-decide; the served bundle still fetches nothing at runtime |
| 08-19 to 08-29 | The engine's factors, and the surface that shows them | Every member rolls and one roll counts, named before the dice are seen; the rain factor made relative to the pool's driest district; «last time we went here» halves a place; the ingredient veto built, measured and withdrawn for want of coverage | rain: gap ÷ 120, floored at 0.5; ingredient coverage 12.4% of places, which is why the kind left the product |
| 08-29 to 08-31 | The surface frozen | The return-choice surface; an eleventh, then twelfth and thirteenth category; the nightly S3 backup with a restore drill | drill: 19.7 MB dumped in 3.7 s, restored in 9.4 s, counts identical |
| 08-30 to 09-02 | The classifier ladder | A 7B model admitted once the comparison ran on the machine the pipeline actually calls; prompts v6 and v7; the test set relabelled twice; the whole city re-decided; the per-model unload that removed a slowdown | four models on one set: 72.0 · 71.0 · 70.5 · 65.5; 36,014 rows in 10.5 h with five level curves; 其他 down 38% |
| 09-04 | The design round | The tonight screen as a menu with section marks, one slim bar on every inner screen; the reveal's chrome receding; connection and rate limits on the proxy; a 25 s heartbeat on the live stream | a stream silent for 130 s: cut through the proxy, open direct; with the heartbeat, open and delivering |
| 09-04 to 09-07 | Launch on EC2 | One small instance in Tokyo boots the public extract and passes one ingest cycle the same day; the box wedged twice on memory; the roster ingest streamed instead of held whole; TLS terminated in the existing nginx with an Origin CA certificate; Cloudflare live in Full (strict) | 49 MB available under one ingest → 398 MB worst case after; the roster 172 → 77 MB; the stack 1,131 → 1,009 MiB at rest; a health check that cost 7.4 s of CPU every 20 s, gone |
| 09-08 | Images from a registry | Seven image names collapsed to three; images built here and pushed to a public registry tagged with the extract's commit; the box pulls that tag and builds nothing | pull 9 s; memory 479 → 664 MB during the deploy, never dipping |
| 09-11 | More than one instance | The event bus moved into the database so two API processes can serve one circle; the schema step left the boot so instances cannot race one migration; each process's listening connection supervised and reported | a listener killed from the database side: 503 in 0.18 s, reconnected in 1.23 s |

## Future work

- **素食 stops being a category and becomes an attribute** a place carries (素食麵館 = 麵食 + 有素),
  because «I cannot eat here» is a requirement on the table and not a discount. The set returns to
  twelve.
- **More than one instance behind a load balancer**, now that the event bus is in the database and
  the schema step is a deploy step.
- **MLflow over the evaluation rounds**, replacing the round files' home-built bookkeeping.
- **A 超市 category and prompt v8** — the test set has to be re-cut first, or the new score is not
  comparable to the current one.
- **Text-to-speech and speech-to-text rounds** for an introduction recording, scored the same way the
  classifier was: a fixed set, a licence check first, and a number per candidate.

## Quick start

```sh
cp .env.example .env                # names only — the comments state the shape of every value
docker compose run --rm migrate     # the schema, once per version
docker compose up -d --wait         # the stack
curl -s localhost:8080/health
#   {"status":"ok","database":"reachable","instance":"…","stream_listener":"up"}
```

**Two commands rather than one**, because the schema step left the stack's boot so that several
instances cannot race it. It is idempotent — run it on a current database and it does nothing.

- **`localhost:8080`** — the app; the API and the database are reachable only over the compose
  network. The Airflow UI has its own port and its own name in `.env.example`, which is where the
  ports live.
- The weather ingest needs a free CWA Open Data key (opendata.cwa.gov.tw), read once at init into a
  Fernet-encrypted Airflow Connection — never from the environment, never into XCom or a rendered
  template field. The five open-data files need no credential. New scheduled jobs arrive **paused**
  (`airflow dags unpause <dag_id>`).

Run an ingest by hand — `0` stored or no change, `1` the source failed, `2` the version signals
disagree — or bring the model up for a backfill:

```sh
docker compose exec api python -m upto.ingest.run_places
docker compose exec api python -m upto.ingest.run_business_tax

docker compose --profile model up -d ollama
docker compose exec ollama ollama pull gemma2:2b
docker compose exec ollama ollama pull snowflake-arctic-embed2
docker compose exec api python -m upto.classify.run 63000010 --rag --embed arctic
#   exit 3 = model absent, nothing written
```

**Lineage is served to a model too**, over MCP on stdio — any reading traces to its publication, its
content hash and the run that wrote it:

```sh
docker compose exec -T api python -m upto.lineage.mcp_server
```

Five tools answer; a sixth, `explain_place_loss`, is listed **only in order to refuse**, because the
trail runs into private per-member choices. A test asserts the refusal.

## Tests

67 test files. Fetch, hash and parse are unit-tested with no network and no database, which is what
keeps the scheduled jobs thin — they supply only *when* and *with which database*:

```sh
python3 api/tests/test_cwa_ingest.py    # and test_fda_ingest, test_fia_ingest, test_dice_table,
python3 api/tests/test_weight_fold.py   # test_classify, test_web_surface, test_evaluate_draw …
```

Integration tests build and drop their own database, in the test-only service that holds the owner's
credential — never in `api`, which connects as a role that cannot `create database`. Every source is
proven idempotent through its real command-line entry point twice, every column compared:

```sh
docker compose run --rm tests python /srv/tests/test_place_ingest_integration.py
docker compose run --rm tests python /srv/tests/test_business_tax_integration.py
```

Every commit passes six local gates in a pre-commit hook — five of them standard-library only, so a
clone needs no toolchain to commit: a secret scan, the `app/` boundary, the font subset against every
member-readable string, the server's copy drawable in the shipped fonts, the hazard register's
numbering, and `ruff` on every staged Python file.

## Privacy

**Authorship dies at the close, in the database.** Closing a round fires a trigger that nulls
`proposal.member_id` for that round, in the transaction that makes the result durable — a trigger
rather than application code, because a manual close over SQL or a fix-up script would each leave
authorship behind and neither would error.

Nothing on the live stream carries a member, and nothing on it carries a timing a member could read:
a preference write returns 204 and emits no event, because in a small circle the moment of an event
is one guess away from a name. Preferences are per meal unless kept, erased nightly by a job whose role
can read and delete that table and nothing else; weather readings older than ninety days go the same
way unless a roll pinned them.

## Scope

Taipei only — twelve districts, one city's open data, addresses normalised at the ingest boundary
because the same government file spells the city two ways. Every source is used inside its licence,
and a source whose licence is non-commercial or uncertain is not used at all; there are no ratings,
no reviews and no scraped pages anywhere in the pipeline. Sized for one small group: live room state
per process, a circle of friends rather than a crowd. A portfolio project, developed in a private
repository and extracted here after every merge, so the commit messages carry the reasoning behind
each change.
