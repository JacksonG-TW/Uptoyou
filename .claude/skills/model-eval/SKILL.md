---
name: model-eval
description: Choose between language models (or prompts, or retrieval settings) for a labelling task by running one evaluation round per candidate against one frozen labelled set and one fixed metric, then comparing them in a round table. Use when asked which model to use for a classification or labelling job, whether a new prompt or retrieval setting is better, or to produce a model comparison someone will make a decision from.
---

# Model evaluation rounds

A decision between models is only as good as the measurement behind it. This skill measures every
candidate the same way, so that the only thing that differs between two numbers is the candidate.

**The method in one line:** one frozen labelled set, one fixed metric, one round per candidate through
the same pipeline, every round a file of rows, and a table built from those files.

`scripts/rounds.py` is a small reference runner (Python standard library only) for an
Ollama-compatible model server. The method does not depend on it: if the project already has a
pipeline, run the rounds through that pipeline instead, and keep the rules below.

## 1. Freeze the test set before the first round

- **Draw once, with a recorded seed**, in proportion to the real data or stratified with a floor per
  stratum so a small stratum can still be scored. Never re-draw between rounds. A new draw is a new set, and its numbers do not compare with the old ones.
- **Label by hand if you can, and name the labeller either way.** A label drafted by a model measures
  agreement with that model, not accuracy. If the labels came from models (one drafting, a second
  cross-checking is common), call the metric agreement, and plan a small human audit of the labels.
- **Record the set's sha256 in every round.** Scoring refuses a round whose sha256 differs from the
  set on disk. A relabel keeps every row in place, so nothing else would notice that the answer key
  moved.
- **A relabel makes a new set.** Keep the old file next to it, because the rounds scored against it
  still stand. Never compare two numbers without checking which set each one names.
- **Say when a category is too small to score.** A category with one row in 200 gives 0% or 100%.
  Print «insufficient rows», never a percentage.
- **A setting chosen on the set is confirmed only on a set it never saw.** Choosing a model, an
  embedder, k or a prompt on the frozen set and then quoting that set's score overstates it. Before
  quoting a tuned score as a result, draw a second set from the same population, label it the same
  way, and run the chosen setting once. Until then, call the score indicative.

## 2. Fix the metric before the first round

- Pick one metric, write it down, and do not change it after seeing results. For single-label
  classification: the share of rows whose answer equals the gold label (accuracy against hand labels,
  agreement against model labels).
- **Work out the set's sampling band before reading any difference.** On n rows at a score p, the 95%
  interval is about ±1.96·√(p(1−p)/n): **about ±6.5 points at 200 rows and 70%**. A difference
  smaller than that band is never a finding, in either direction. The difference between two
  independent scores is noisier still (about √2 wider, ~±9 points here), so to claim a difference,
  run the paired test: both candidates on the same rows, compared row by row (McNemar's test).
- **A refusal is wrong.** An answer outside the allowed labels is not repaired or fuzzy-matched. Count
  refusals separately as well, because a model that refuses often and one that is confidently wrong
  have different problems.
- **Recompute the score from the rows** every time. Never copy a number from an earlier report.

## 3. One round per candidate, through the same pipeline

- **Ask through the pipeline that will run in production**, with the same prompt and parsing and the
  same validation. A separate copy written for the evaluation measures the copy, not the product.
- **Pin each round.** It records the model, the prompt's sha256, the label list's sha256, the test
  set's sha256, and the retrieval settings, and the file name carries a digest of all of them. A run
  that differs in any of these is a new round, written to a new file; the old round is kept
  beside it.
- **Rounds are resumable.** Save every few rows. After an interruption, continue at the first
  unanswered row. A slow local model or a hosted quota can take hours, so a crash must not cost the
  whole round.
- **Run on the hardware that will serve.** Memory limits and timeouts are part of what is being
  chosen. A round on a bigger machine measures a different system.
- **One candidate on the server at a time.** Unload a model before warming the next. A round run
  beside another workload measures the contention, not the model.
- **Expect the first call to a cold model to fail.** It may come back as a dropped connection rather
  than a slow answer. Warm each model with a retry before its round starts.

## 4. Measure retrieval per model

If the prompt includes retrieved examples (labelled look-alikes, as in RAG), treat retrieval as its
own variable:

- **Run each model with and without retrieval.** The same examples help one model and confuse
  another.
- **Leave the asked row out of its own examples.** If the crib (the labelled examples) contains the
  test row, retrieval hands the model the answer.
- **Screen the embedding model on its own first.** Use the nearest neighbour's label as the answer,
  leave-one-out, on the same set. It is cheap and ranks embedders without a generator involved.
- **The number of examples (k) is a variable too.** Record it in the round, and refuse to continue a
  round at a different k.
- **Keep the crib away from hosted models** if the labels are private: the crib is the answer key.

## 5. The round table

Build it from the round files, one row per round: model, prompt version, retrieval, test set, correct
out of N, the score, its band, refusals. A round that is not complete shows «incomplete» and no
percentage.

**Then decide on more than the top number.** When the leaders sit inside each other's band, they are
tied: cost per row, memory, licence and what is already running decide. Write down why the winner won,
and give the measured reason, not a remembered one.

## Traps met in practice

- **A stale image or build.** The runner in the container was last week's code, and it produced a
  number that looked exactly like a real one. Before a round, check that the code that runs is the
  committed code (compare a file hash inside the container with the repository's), and **refuse to
  start** on a mismatch rather than warning. A round is hours long.
- **A prompt that reads better is not a better prompt.** A clearer, more careful revision scored
  49.5% against the old prompt's 51.5%. That two-point drop is inside the band, so it is not a finding,
  but neither is the improvement the better reading promised. Judge prompts by rounds, and read rounds
  against the band.
- **Model size does not predict memory.** Load the model and look at what it uses; never size from
  the file on disk. In one measurement the smallest file (an embedding model) used about 3.7× its size
  on disk.
- **A missing model looks like a quiet day.** A model name that is not pulled, or a server name that
  does not resolve, fails the same way as a server that is down. Check the server's model list before
  the round.
- **A file inside a container dies with the container.** Write round files and logs to a mounted host
  directory from the first line.

## Running the reference script

```
export OLLAMA_URL=<OLLAMA_URL>
python3 scripts/rounds.py run --set testset.json --labels labels.txt --prompt prompt.txt --model <MODEL>
python3 scripts/rounds.py run --set testset.json --labels labels.txt --prompt prompt_rag.txt --model <MODEL> \
    --crib crib.json --embed-model <EMBED_MODEL> --k 5
python3 scripts/rounds.py score rounds/round_<...>.json --set testset.json
python3 scripts/rounds.py table rounds/*.json --set testset.json
```

- `testset.json` is a list of `{"id", "input", "gold"}`; `crib.json` is a list of `{"input", "gold"}`.
- `prompt.txt` uses `{input}`, `{labels}` and `{examples}`; they are replaced, not formatted, so
  braces elsewhere in the prompt are safe.
- **The test set, and the crib if given, are sent to `OLLAMA_URL`.** Point it at a server you trust
  with them. urllib honours `http_proxy`/`https_proxy`, so unset them if the data must not pass through
  a proxy.
- Exit 3 means the server did not answer and progress is saved: run the same command again.
  Exit 1 means something a re-run will not fix: the server answered with an error (a model that is
  not pulled, for example; the message says which), the test set has duplicate ids, or `score` was
  given a round that is incomplete or was run against a different test set.

## A worked example

A restaurant-cuisine classifier: about 36,000 restaurant names, thirteen categories, small local models.
These rounds ran through the project's own classification pipeline, not through `scripts/rounds.py`.

- **Set:** 200 names from one district's names, drawn once with a fixed seed, stratified over the
  three kinds of name with at least 30 per stratum so the small strata stay scorable. The labels
  were drafted by one model and cross-checked by a second, not written by a person, so every number
  below is **agreement with those labels**, not accuracy. The band at 200 rows is about ±6.5 points.
  The retrieval settings were chosen on this same set, and no second set was drawn.
- **Retrieval, per model:** five retrieved look-alikes moved a 2B model 51.5% → 61.0% (+9.5: outside
  the ±6.5 band for one score, and just past the ~±9 band for a difference) and a 3B model
  37.0% → 58.0% (+21), both on the same 200 rows. The paired test was not run. Another 3B model went
  51.0% → 48.5%, inside the band: no gain.
- **The table, after a relabel to thirteen categories (a new set, so not compared with the numbers
  above):**

| Model | Agreement on the 200 |
|---|---|
| `qwen2.5:7b-instruct` | 72.0% |
| `gemma2:2b` | 71.0% |
| `llama3.2:3b` | 70.5% |
| `qwen2.5:3b-instruct` | 65.5% |

- **The decision:** the top three sit within 1.5 points, a tie inside the band. The 2B was already in
  use, and its full pass over all 36,014 names took 10.5 hours; the 7B was estimated at about 10.8,
  so cost did not separate them either. So the 2B stayed.
- **No person has audited these labels yet.** A sample audit is what would turn agreement into
  accuracy.
