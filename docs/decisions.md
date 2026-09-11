# The long version

The README states each decision in a paragraph. This page holds the measurements behind four of
them — the ones where the first number was wrong, or where the same question was measured twice
and the second answer replaced the first. It is here so the README can stay short without the
working being thrown away.

Every figure names the date it was taken and the thing it was taken on. Where two figures for the
same quantity disagree, both are here with the reason.

---

## Industry codes: what a second measurement changed, and what it did not

The README's decision 6 says the tax registry's official industry codes settle about one row in
ten, and that they sharpen the classifier rather than replacing it. That came from a city-wide
join. It was then measured again on the 200-row evaluation set, which is the harder test: those
rows are the ones actually scored.

**The accuracy quoted beside the first version of this was 66.0%** — `gemma2:2b` with retrieval on
`testset_v1` under prompt v5 (`round_gemma_v5-rag-2026-08-15_arctic.json.report.md`). The same
model and configuration now reads **71.0%** on `testset_v3` under prompt v7.

**The join figures below did not move with it, and that is not luck.** The 200 rows were drawn once
and frozen; v1, v2 and v3 are the same rows in the same order, relabelled. So «142 of 200 join a
tax row» is a fact about the draw, not about the prompt that scored it.

- **142 of 200 rows join a tax row, and 75 of those are a chain's HQ registry number.** The
  guardrail against calling a multi-site company non-food from its code alone is the majority case,
  not the exception.
- **The upper bound on a code rule is +13 rows of 200, and it is an oracle bound** — it assumes you
  already know which codes to trust. Strip the codes seen on fewer than four rows and the
  defensible upside is **+4 rows, 2 points**.
- **The instructive row is 茶葉批發**: a wholesale code on four HQ numbers, three of them drinks
  shops. A non-food verdict from that code would have been wrong three times in four.

Which codes may decide, and what they may decide, is a mapping that has to be argued from the
registry's own semantics rather than fitted to 200 rows. That work has not been done, and the codes
are stored and read by nothing.

---

## The GPU pass: three measurements, and the first two were of the wrong thing

The README's decision 8 gives one number — **1.27 s a name** on the home box's 8 GB card, against
12–19 s a name on its CPU. Here is what happened after that number was taken.

### The card was waiting, not computing

At 1.27 s a name the GPU sat at **0–47% utilisation and a quarter of its power cap**. Timing each
call separately found the reason: a round trip with no model work costs 48 ms, but every request
carries **~475 ms of fixed cost that scales with nothing** — not the input length, not the output
length, not the link. Two calls per name, so ~950 ms of the 1,270 was paid per *request* rather
than per name.

**So the fix was to make fewer requests, not faster ones.** The retrieval crib embedded one name
per call; a commit batch of 25 names now embeds in one call, and that half went **0.481 → 0.045 s
a name — 10.8×**, measured twice on the same 100 names.

*Rejected:* issuing several names concurrently. It measured 2.6× on the generation half and
saturated at four in flight, and it was declined for a reason that is not about speed: a pass
commits every 25 rows and resumes at the first undecided one, and N requests in flight is both N
connections that can drop and an end to that clean frontier. A dropped connection had already
killed one pass at row 400 of 3,324. It is now retried three times, and the retry count is printed
so a flaky link reads as a number rather than as a slow night.

### The pass then slowed as it ran

A 2,912-row run began at **0.92 s a name and degraded steadily to about 2.0**. Four townships on
two builds bent the same way — **1.7× first-to-last**.

Sampling the model server's memory during a round showed the cause: it keeps one saved prompt state
per distinct prompt, **unbounded** — about **100 MB per request** for the 2B model — until the 8 GB
box killed it once. The cost is per (model × prompt version), and parameter count predicts nothing:
measured on prompt v7, `gemma2:2b` ~103 MB per request, `llama3.2:3b` ~79, the 7B ~36, the 3B ~23.
**The 2B is the expensive one.**

The fix is to unload the model every N rows, N chosen per model (25 for `gemma2:2b`). It costs a
ten-second reload and holds the curve level: the whole-city re-pass ran **36,014 rows in 10.5 h
with five flat curves**, and the one district whose result had contradicted the model no longer
does.

### Why two hosts report different place counts

The classification runs where the GPU is, which is neither the serving instance nor the development
box's CPU, so classified rows are **copied** to the instance rather than produced on it. Each host
also runs the reference ingest for itself, and the published file moves.

On 2026-09-07 the instance's own publication no longer carried **532** of the registry numbers the
classification had been run against — closed or deregistered since — and those rows were deleted
there, because the newest publication is the truth about what is open and a place the source no
longer lists is one the product cannot show.

So four numbers for what sounds like one quantity. **Each is named by its table and its host**,
because the earlier version of this table named neither and one row was mislabelled for it —
35,965 was called a reference count and is a `place` count (found 2026-09-11, when the instance and
the development database were read side by side):

| Number | Table | Host | What it is |
|---|---|---|---|
| **35,965** | `place` | launch instance | the places a circle can choose |
| **36,376** | `reference_place` | launch instance, and the development database's **current** publication (2026-09-02) | the reference file as published on 2026-09-02 |
| **36,497** | `place`, origin `reference` | development database | one per reference row ever seen; accumulates across publications and is not pruned (a 36,498th row is one circle's own place) |
| **36,499** | `reference_place` | development database, publication of **2026-08-11** | the first publication. Kept here because measurements were quoted against it until 2026-09-11 |

**36,499 is the FIRST publication, not the current one.** The reference file moved on 2026-09-02 and
the current one carries 36,376. The README's name-ladder figures were measured against 36,499 until
2026-09-11, when the probe was re-run against the current publication and the page's four reach
figures moved with it — so nothing public quotes 36,499 any more.

**The 532 between 36,497 and 35,965 is the source moving, not a failure.** On 2026-09-07 the
instance's own publication no longer carried 532 of the registry numbers, and those rows were
deleted there; the development database keeps its `place` rows across publications, so it still has
them. It closes on the next city pass, or when the classifier's output ships nightly instead of by
hand.

**The 411 between the instance's 36,376 and its 35,965 is an open measurement.** The instance holds
fewer `place` rows than its current publication has `reference_place` rows, and nothing here has
measured why. No cause is stated because none has been taken.

---

## The memory week: a 2 GB instance and its own nightly work

The README's decision 10 says the instance was too small for its nightly work and that the fix was
measured before it was chosen. The measurements arrived in this order, over **2026-09-04 to 09-07**,
and the first one was wrong about the cause.

**Night one — the wrong culprit.** Eight scheduled jobs unpaused in one loop wedged the box while
every cloud health check stayed green. Walked one at a time, the registry roster left **49 MB** free
against a 150 MB floor. The roster ingest was found holding **209,472 row objects** until the write
ended; streamed in 5,000-row chunks its peak fell **172 → 77 MB**, with the stored rows identical.

**Night two — the real cost.** With the ingest fixed the box still crawled: Airflow itself sat
at about **1.35 GB idle**, and two tasks starting in the same minute left the box crawling for
twelve hours **with no out-of-memory line anywhere** — the failure that looks like everything
working, only slower.

**The table that produced the fix**, measured on a scratch stack rather than on the live box: one
task at a time, the log server off, one parser process, and health checks every 120 s take the whole
stack **1,131 → 1,009 MiB at rest**.

**And the box's mysterious 80% idle CPU was the health check itself** — a **7.4-second** CLI cold
start every 20 seconds, on two services.

Afterwards every scheduled job ran one after another with the worst reading at **398 MB** free and
the kernel's kill counter at zero. The instance stayed small.

*Rejected along the way:* a bigger instance first (chosen, then refused by the account's plan);
a swap file, which turns a crash into a twelve-hour crawl rather than preventing either; and tuning
without a table, which is how the first night blamed the ingest.

---

## Eight habits, each with one instance

The code is one third of this repository. The other two are the reasoning behind each choice and the
instruments that checked it.

**One decision at a time, with a recommendation, its cost, and the branch turned down.** Every
choice is written down once, with a date, and the README's eleven decisions are the digest.
*Instance:* the launch surface's structure was re-decided three times after a «final» build in early
September — so a screen's structure is now settled once from a wireframe and a feature list, before
anything is built.

**Measure before deciding, and check the instrument before blaming the product.** A number beats an
adjective. *Instance:* the memory week above — the first reading blamed the ingest and the cause was
Airflow's own footprint plus a health check that cold-started a CLI every 20 seconds. On
one day, seven of nine red findings were a test harness measuring itself, so each harness now writes
down what would make it report a defect if the product were fine.

**Checks run on the committer's machine, not in CI.** Six pre-commit gates, five of them
standard-library only, so a fresh clone needs no toolchain to commit; CI re-runs the tests and
decides nothing. *Instance:* the font-subset check refuses a commit whose member-facing copy needs a
glyph the shipped fonts lack — a gap that is invisible on any machine with a system CJK fallback, so
that check is the only place it shows.

**The writer never judges its own work.** The served surface is judged from the page and the wire by
a reader that never sees the builder's reasoning; every backend change is read against the reasoning
it cites and the tests it names before a build is treated as releasable; visual choices are settled
from rendered pages, never from prose. *Instance:* the first day of independent code review found
two faults in a build that every test and the boot check had passed.

**Licence-clean, or not used.** Every source and every model carries its licence before it is
touched. *Instance:* `qwen2.5:3b-instruct` is research-licensed, so it may be asked in an evaluation
round and can never be a pipeline's model. The same rule sorted the text-to-speech candidates — four
usable, four refused, two uncertain and therefore out.

**Provenance over prediction.** Publications are content-addressed and never overwritten; each one
records the shape of the file it came from; every weight that moved a place's odds is a row pinned
to the reading it was computed from. *Instance:* a dropped table replays from what the ledger kept,
and a reveal can name the run each factor came from.

**The product states; it never advises.** Weather is shown as information and never as a reason to
go somewhere; the reveal itemises what happened and recommends nothing. *Instance:* «the rain made
this place less likely» is a stored row a member can read; «you should pick the dry one» is a
sentence the surface cannot produce.

**Off-the-shelf where the shelf is better.** The first surface was hand-rolled with no build step
and no framework; on 2026-08-18 it was rebuilt on React 19 + Vite, because hand-rolling was too slow
for what the screens needed. The same rule brings in MLflow rather than keeping a home-built
equivalent.

---

## The short entries in full, and the figures that left the page

Two things live here. **The six decisions the README states in one line each** — it says «the long
version has each of these in full», and this is that. And **the measurements that left the page
when it was reshaped for a reader deciding whether to read further**: none was withdrawn, they are
here so that README + this page together still hold every figure the longer page carried.

### How fresh the data is, derived from the ledger rather than from what a publisher claims

Two different things, kept apart on purpose: how long after a source republishes we are guaranteed
to have noticed (ours, bounded by the poll), and how often it actually republishes (theirs,
observed).

| Source | Detected within | Republishes every | So the data is |
|---|---|---|---|
| CWA township forecast | 62 min | 4.3 h median, 8.1 h worst | at most 9.1 h old |
| CWA station observation | 62 min | 60 min median, 62 min worst | at most 2.1 h old |
| 營業稅籍 registry | 24.0 h | 24.0 h median, 36.2 h worst | at most 2.5 d old |
| FDA 餐飲場所 reference | 24.0 h | insufficient history: 1 publication | not yet derivable |
| 食材登錄 brands | 24.0 h | insufficient history: 1 publication | not yet derivable |
| 衛生評核 signs | 24.0 h | insufficient history: 1 publication | not yet derivable |
| 商業登記 status | 24.0 h | insufficient history: 1 publication | not yet derivable |

**The four incomplete rows are a state, not a gap in the work.** A source seen once has published
once in this history, and *n* publications yield *n−1* intervals; the cell fills itself as the jobs
run. What it will not do is borrow the number the publisher advertises — the roster calls itself
monthly and the tax extract is cut monthly, and neither is something this pipeline observed. A cell
sourced from a web page would wear the same formatting as the measured seconds beside it and mean
something entirely different.

The half that *is* ours is a real bound and holds for all seven: no poll was missed in the window,
and the longest stretch with no successful run was 62 minutes on the hourly sources and one day on
the daily ones. Over the same 8 days the scheduler ran **361 task instances** and lost two — both on
the township forecast, 162 of 164.

### What is inside the tax file, and what is never written

**A 66 MB zip holding one ~320 MB CSV of 1,711,012 rows** — every registered business in the
country. Only rows whose 統編 already appears in the latest reference publication are stored:
**14,521 kept against 19,203 reference numbers, in about 15 seconds**, on the day the README's
figure was taken. Everything else is never written — a storage decision rather than an
optimisation: a tax row for a hardware store two hundred kilometres away answers nothing this app
asks.

**Four numbers that sound like the same one, reconciled** (the middle two measured on the
development database, 2026-09-11):

| Number | What it is |
|---|---|
| **1,711,012** | rows in the CSV |
| **~14,560** | rows kept **per publication** — one per 統編, no duplicates: the newest publication here holds 14,561 rows and 14,561 distinct 統編 |
| **14,521** | that same per-publication figure on the day the README quotes |
| **72,801** | `business_tax_row` on the launch instance — the table **accumulates**, one set of rows per publication it has seen, and at ~14,560 a publication that is about five of them |

So «the rest is never written» is about **1.696M rows per run**, not a one-off: each publication
keeps its own ~14,560 and discards the rest again.

The reference file has the same shape one size down: a 99 MB CSV of **827,784 rows**, of which the
Taipei restaurant rows are kept — 36,499 in the publication of 2026-08-11, 36,376 in the current
one.

### Substring search: why the index was turned down

*The README's «a trigram index changed the plan for 0 of 31 realistic queries».*

The typeahead matches with `ILIKE '%q%'`. The obvious fix is `pg_trgm` + GIN on the three searched
columns. Measured on 31 realistic queries, it **changed the plan for none of them** and left p50 at
**311 → 324 ms** — slightly worse, within noise.

**Two reasons, and the second is the one nobody would guess.** The predicate ORs a base column
against two lateral outputs, so the filter cannot reach an index on the base column at all. And the
cluster runs a deterministic **`C` locale**, under which `pg_trgm` emits **no trigrams for 96.2% of
the names** — CJK text produces nothing for it to index. The similarity-operator rewrite returned
zero rows for every CJK query and was refused.

**The scan was never the cost.** A per-row lateral brand lookup executed **35,533 times per
keystroke** is **93% of the query's buffers**; the reference table is about 1%. Expressed as one
grouped join it is **61× fewer buffers**, with the result set proved identical (`except all` empty
both ways over the whole publication).

### Why pgvector rather than a second service

*The README's «the crib is 537 rows across three embedders».*

The retrieval crib is **537 rows per embedder**, three embedders, thousands of vectors at the
outside. A dedicated vector store (Pinecone, Milvus, Qdrant) buys nothing at that size and costs one
more stateful service to run, back up, monitor and keep a version of. `pgvector` is an extension on
a database the stack already has, so the crib is in the same dump as everything else and needs no
second backup story.

*Turned down, and the condition that would reverse it:* a crib large enough that index build time or
memory becomes the constraint rather than the query. Nothing here is close.

### Why the evaluation set is frozen

*The README's «it caught a prompt that read better and scored worse».*

200 names, drawn once with a fixed seed, stratified over the three name rungs with a floor of 30 per
stratum so the small sign and brand strata stay scorable. Labels drafted by a frontier model and
cross-checked by a second, recorded per row — so a score reads «agreement with the teacher», never
ground truth.

**What it bought, in one instance:** prompt v4 read better than v3 to a person and scored **51.5 →
49.5** on the set. Without a frozen set that revision ships on the strength of reading well. That is
the only thing a fixed set exists to do, and it did it once in the first fortnight.

The draw has never been re-run. v1, v2 and v3 are the same 200 rows in the same order, relabelled
under a ruling; every report carries the set's sha256 so two scores compare only when it matches.

### Why the live stream sends a heartbeat

*The README's «a stream silent for 130 s was cut».*

Through the proxy, a stream that said nothing for **130 seconds was cut**, and a real event
afterwards was delivered to nobody. Direct to the origin the same stream stayed open and delivered —
same code, same seconds, side by side, twice. With a comment line every **25 s** the same probe
through the same hostname reads open and delivering.

**Why this was a launch blocker rather than a polish item:** a circle that has said nothing for two
minutes is the normal case for this product, not an edge. *Turned down:* an unproxied hostname,
which gives up the shield the domain exists for; and reconnect-and-hope, which cannot tell a cut
stream from a quiet one. The comment line carries no timing a member could read.

### Two join rates the README states as shares

- **The brand join: 188 of 266 companies join** the current publication. A multi-brand company
  keeps its registered name, so the rate is not a defect to close.
- **The tax address disagrees with the storefront on 89.8% of matched rows, and 13.7% are
  registered outside the city entirely.** That is why nothing may join on it.

### The classifier's own footprint

The quantized 3B model peaks around **2.1 GB** while a backfill runs, which is why it sits behind a
profile and is off otherwise. The deployment target has 4 GB.

### The backup drill

A nightly `pg_dump` to S3 under a read-only role, thirty kept, swept only after a successful upload.
The drill on the **338 MB** development database took **3.7 s to dump and 9.4 s to restore**, with
`alembic current` and the row counts of nine tables identical on both sides. The serving instance's
own dump is **31.2 MiB in 12 s**.

### One figure deliberately dropped rather than moved

The README used to state the serving stack at rest **twice** — 942 MiB in one decision and 1,009 MiB
in another, measured on different days and both true when written. One number per fact: the page now
states 1,009 MiB, which is the one measured after the shrink that both decisions are about.

### A score that is a different experiment, not a better one

Two of the four rounds have `_brandcrib` variants, run with an authored brand crib added. They read
**2.5 to 4.0 points higher** and are not comparable with the four in the README's table: a different
crib is a different configuration, so it gets its own round rather than a better number for the same
one.
