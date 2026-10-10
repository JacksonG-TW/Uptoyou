"""The classifier's scheduled pass runs only on a host that says so (2026-10-10).

The production instance runs the same reference ingest, so it emits the asset that schedules
`upto_place_classify_backfill`; it must never classify (it cannot reach the GPU, and its categories
are carried by hand from the development database). The DAG arrives paused there, and this gate is
what holds if it is ever unpaused: a short circuit that skips the run — no failure, so no alert —
unless `UPTO_CLASSIFY_HOST` is exactly "1".

Host-side and structural: Airflow is not importable here, so the DAG's source is read. The gate's
behaviour under each value is measured in the Airflow image (the commit that added it says how).

Run: python3 app/api/tests/test_classify_host_gate.py
"""

import ast
import pathlib
import re
import unittest

APP = pathlib.Path(__file__).resolve().parents[2]
DAG = APP / "airflow" / "dags" / "place_classify_backfill.py"
COMPOSE = APP / "compose.yaml"
EXAMPLE = APP / ".env.example"


class TheClassifierRunsOnlyWhereItIsAllowedTo(unittest.TestCase):
    def setUp(self):
        self.source = DAG.read_text(encoding="utf-8")
        self.tree = ast.parse(self.source)

    def gate(self):
        for node in ast.walk(self.tree):
            if isinstance(node, ast.FunctionDef) and node.name == "this_host_classifies":
                return node
        self.fail("no this_host_classifies task in the DAG")

    def test_the_gate_is_a_short_circuit(self):
        decorators = [ast.unparse(d) for d in self.gate().decorator_list]
        self.assertTrue(any(d.startswith("task.short_circuit") for d in decorators), decorators)

    def test_it_opens_only_on_exactly_one(self):
        body = ast.unparse(self.gate())
        self.assertIn("os.environ.get('UPTO_CLASSIFY_HOST', '') == '1'", body)

    def test_it_comes_first(self):
        wiring = [line.strip() for line in self.source.splitlines() if ">>" in line and "(" in line]
        self.assertTrue(wiring, "no task wiring found")
        self.assertTrue(wiring[-1].startswith("this_host_classifies() >> model_service_up()"), wiring)

    def test_compose_passes_it_off_by_default(self):
        self.assertRegex(COMPOSE.read_text(encoding="utf-8"),
                         r"UPTO_CLASSIFY_HOST: \$\{UPTO_CLASSIFY_HOST:-0\}")

    def test_the_example_env_documents_it_off(self):
        self.assertTrue(re.search(r"^UPTO_CLASSIFY_HOST=0$", EXAMPLE.read_text(encoding="utf-8"), re.M))


if __name__ == "__main__":
    unittest.main(verbosity=1)
