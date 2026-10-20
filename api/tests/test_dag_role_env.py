"""A DAG that hands the pipeline the ingest role's URL hands it under the ingest role's name.

The pipeline CLIs read `UPTO_INGEST_DATABASE_URL` first (D115). A DAG that set only
`UPTO_DATABASE_URL` still connected as `upto_ingest` — that is the Connection it reads — but the
CLI took the fallback and printed that it was the OWNER's connection, a line that sends a reader
after a role-split breach that never happened. Measured in the Airflow image, 2026-10-20: with
only the old variable, the fallback line and `current_user = upto_ingest`; with both, no line and
the same role.

Host-side and structural: Airflow is not importable here, so each DAG's source is read.

Run: python3 app/api/tests/test_dag_role_env.py
"""

import pathlib
import re
import unittest

DAGS = pathlib.Path(__file__).resolve().parents[2] / "airflow" / "dags"
INGEST_CONNECTION = re.compile(r'^POSTGRES_CONNECTION = "upto_ingest_postgres"$', re.M)
SETS_URL = 'environment["UPTO_DATABASE_URL"] = _database_url()'
SETS_ROLE = 'environment["UPTO_INGEST_DATABASE_URL"] = environment["UPTO_DATABASE_URL"]'


def ingest_dags_that_hand_over_a_url():
    for path in sorted(DAGS.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        if INGEST_CONNECTION.search(source) and SETS_URL in source:
            yield path.name, source


class TheIngestRoleArrivesUnderItsOwnName(unittest.TestCase):
    def test_there_is_something_to_check(self):
        # Four today; a refactor that renamed the line would otherwise pass this file vacuously.
        self.assertGreaterEqual(len(list(ingest_dags_that_hand_over_a_url())), 4)

    def test_every_one_also_sets_the_role_variable(self):
        for name, source in ingest_dags_that_hand_over_a_url():
            with self.subTest(dag=name):
                self.assertEqual(source.count(SETS_URL), source.count(SETS_ROLE))
                self.assertGreater(source.index(SETS_ROLE), source.index(SETS_URL),
                                   "the role variable copies the URL, so it must come after it")


if __name__ == "__main__":
    unittest.main()
