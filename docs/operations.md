# Running it

The README's Quick start brings the stack up. This page is everything you do after that: running an
ingest by hand, a classification backfill, and asking the pipeline where a reading came from.

## Run an ingest by hand

An ingest exits **0** for stored or no change, **1** when the source failed, and **2** when the
file's own version stamp and its content hash disagree about whether anything changed — the printed
verdict says which way and what was written. Only the place and tax sources can exit 2; the others
read a bare CSV with no stamp, so there is no second version signal to disagree with the hash.

```sh
docker compose exec api python -m upto.ingest.run_places
docker compose exec api python -m upto.ingest.run_business_tax
```

The weather ingest needs the CWA key to be in place first — see the README's Quick start. The five
open-data files need no credential.

## Classify a district

The model is behind a compose profile and is off unless a backfill is running.

```sh
docker compose --profile model up -d ollama
docker compose exec ollama ollama pull gemma2:2b
docker compose exec ollama ollama pull snowflake-arctic-embed2
docker compose exec api python -m upto.classify.run 63000010 --rag --embed arctic
#   exit 3 = the model service is not up, and nothing was written
```

**Exit 3 is ordinary rather than a failure**, and nothing is written on that path. A pass commits as
it goes, so an interrupted run resumes at the first undecided row.

## Ask where a reading came from

Lineage is served to a model too, over MCP on stdio. Any reading traces to the fetched file it came
from, that file's content hash, and the run that wrote it:

```sh
docker compose exec -T api python -m upto.lineage.mcp_server
```

Five tools answer: `run_history`, `run_detail`, `publication_detail`, `forecast_reading_source` and
`observation_reading_source`. A sixth, `explain_place_loss`, is listed **only in order to refuse** —
the trail runs into private per-member choices, and a tool that merely lacks a feature today grows it
the first time somebody finds it useful. A test asserts the refusal.

## Run the tests

Two tempos. **Host-side** needs no network and no database:

```sh
python3 api/tests/test_cwa_ingest.py    # and test_fda_ingest, test_fia_ingest, test_dice_table,
python3 api/tests/test_weight_fold.py   # test_classify, test_web_surface, test_evaluate_draw …
```

**Build-and-drop** tests build their own database and drop it. They run in the test-only service
that holds the owner's credential, never in `api` — which connects as a role that cannot
`create database`:

```sh
docker compose run --rm tests python /srv/tests/test_place_ingest_integration.py
docker compose run --rm tests python /srv/tests/test_business_tax_integration.py
```

## Read the run ledger

Per source: how many runs stored something, how many found nothing new, how many failed, and when
the last one finished. A source that goes quiet shows up as a stale `max`, not as an absence.

```sh
docker compose exec db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "select source, outcome, count(*), max(finished_at) from ingest_run group by 1, 2 order by 1, 2"'
```
