#!/usr/bin/env python3
"""A28 question 1 — the value checks' rules, host-side: no network, no database, no Airflow.

Run: python3 app/api/tests/test_value_check.py

What is pinned here (owner-ruled 2026-09-15, «A28 question 1 … the light option» and «A28's checks
read through a new read-only check role»):

1. **The rules are pure and say the right sentence.** A stale source alerts with a sentence naming
   the source and the hours; a fresh one records `ok`; a value the statement could not produce is
   recorded and never alerts.
2. **The forecast's raw row count carries no line** — 1,376 rows after 6,720 is a `recorded` row,
   never a finding (the backtest's 60–90 false alarms).
3. **Every threshold is a named constant with a source line, and every source the ledger names
   has one of each** — the map and the constants cannot drift apart.
4. **The DAG helper imports without Airflow**, like `_publication_check.py`, so the DAG-parse
   hazard (H46) cannot hide a broken rule.
5. **A finding composes into one A10 message** through `_alerts.compose_message`, and the message
   still names the source and the hours after the detail cap.
"""

from __future__ import annotations

import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
DAGS = os.path.join(HERE, "..", "..", "airflow", "dags")
sys.path.insert(0, DAGS)
os.environ.setdefault("UPTO_SRC", os.path.join(HERE, "..", "src"))

from upto import checks  # noqa: E402


def values(**kwargs):
    base = {"hours_since_last_run": 0.2, "failed_24h": 0, "hours_since_last_stored": 0.5,
            "rows": 100, "previous_rows": 100, "payload_bytes": 1000}
    base.update(kwargs)
    return base


class Rules(unittest.TestCase):
    def test_a_stale_source_alerts_with_the_source_and_the_hours(self):
        metrics, findings = checks.evaluate("O-A0001-001", values(
            hours_since_last_stored=10.0, stations=19, reading_rows=171))
        self.assertEqual([f.metric for f in findings], ["hours_since_last_stored"])
        self.assertIn("O-A0001-001", findings[0].sentence)
        self.assertIn("10.0 h", findings[0].sentence)
        self.assertIn("3.0 h", findings[0].sentence)  # 1.0 h interval × 3
        alerts = [m for m in metrics if m.verdict == "alert"]
        self.assertEqual(len(alerts), 1)

    def test_a_fresh_source_records_ok_and_nothing_alerts(self):
        metrics, findings = checks.evaluate("O-A0001-001", values(stations=19, reading_rows=171))
        self.assertEqual(findings, [])
        by_metric = {m.metric: m.verdict for m in metrics}
        self.assertEqual(by_metric["hours_since_last_stored"], "ok")
        self.assertEqual(by_metric["stations"], "ok")
        self.assertEqual(by_metric["reading_rows"], "ok")
        self.assertEqual(by_metric["failed_24h"], "recorded")

    def test_the_forecasts_raw_row_count_carries_no_line(self):
        metrics, findings = checks.evaluate("F-D0047-061", values(
            hours_since_last_stored=2.0, reading_rows=1376, payload_bytes=570000, townships=12))
        self.assertEqual(findings, [], "a partial CWA publication is ordinary, never a finding")
        rows = [m for m in metrics if m.metric == "reading_rows"][0]
        self.assertEqual((rows.value, rows.verdict), (1376.0, "recorded"))
        self.assertIsNone(rows.threshold)
        self.assertNotIn("rows", checks.statements_for("F-D0047-061"))
        self.assertNotIn("previous_rows", checks.statements_for("O-A0001-001"))
        self.assertNotIn("F-D0047-061", checks.ROW_STEP_SOURCES)
        self.assertNotIn("O-A0001-001", checks.ROW_STEP_SOURCES)

    def test_coverage_drift_on_the_weather_pair_alerts(self):
        _, findings = checks.evaluate("F-D0047-061", values(hours_since_last_stored=1.0, townships=11))
        self.assertEqual([f.metric for f in findings], ["townships"])
        self.assertIn("11 townships", findings[0].sentence)
        self.assertIn("12", findings[0].sentence)

    def test_a_row_step_on_a_nightly_source_alerts_either_way(self):
        _, down = checks.evaluate("fia-business-tax", values(rows=12000, previous_rows=14000))
        _, up = checks.evaluate("fia-business-tax", values(rows=15500, previous_rows=14000))
        _, flat = checks.evaluate("fia-business-tax", values(rows=14100, previous_rows=14000))
        self.assertEqual([f.metric for f in down], ["row_step"])
        self.assertIn("-14.3%", down[0].sentence)
        self.assertEqual([f.metric for f in up], ["row_step"])
        self.assertEqual(flat, [])

    def test_an_absent_value_is_recorded_and_never_alerts(self):
        metrics, findings = checks.evaluate("taipei-foodtracer", values(
            hours_since_last_stored=None, rows=None, previous_rows=None, hours_since_last_run=None))
        self.assertEqual(findings, [])
        for m in metrics:
            self.assertIn(m.verdict, ("recorded", "ok"))
        stored = [m for m in metrics if m.metric == "hours_since_last_stored"][0]
        self.assertIsNone(stored.value)

    def test_a_source_with_one_publication_has_no_line_yet(self):
        # foodtracer and hygiene-grade have published once: no interval to measure, so a large
        # number is recorded, not raised — the constant is None on purpose.
        metrics, findings = checks.evaluate("taipei-hygiene-grade", values(hours_since_last_stored=900.0))
        self.assertEqual(findings, [])
        self.assertIsNone(checks.PUBLICATION_INTERVAL_H["taipei-hygiene-grade"])

    def test_the_nightly_freshness_names_the_silent_source_only(self):
        rows = [("F-D0047-061", 0.3), ("O-A0001-001", 0.3), ("fda-97", 5.0), ("taipei-foodtracer", 5.0),
                ("taipei-hygiene-grade", 60.0), ("gcis-restaurant-registry", 4.6), ("fia-business-tax", 4.3)]
        metrics, findings = checks.freshness(rows)
        self.assertEqual([(f.source, f.metric) for f in findings], [("taipei-hygiene-grade", "hours_since_last_run")])
        self.assertIn("60.0 h", findings[0].sentence)
        self.assertIn("48.0 h", findings[0].sentence)  # 24 h × 2
        self.assertEqual(len(metrics), len(checks.SOURCES))

    def test_freshness_records_a_source_the_ledger_never_saw(self):
        metrics, findings = checks.freshness([("F-D0047-061", 0.5)])
        self.assertEqual(findings, [])
        never = [m for m in metrics if m.source == "fia-business-tax"][0]
        self.assertEqual((never.value, never.verdict), (None, "recorded"))


class Constants(unittest.TestCase):
    def test_every_source_has_a_cadence_an_interval_and_a_publication_table(self):
        for source in checks.SOURCES:
            self.assertIn(source, checks.RUN_CADENCE_H)
            self.assertIn(source, checks.PUBLICATION_INTERVAL_H)
            self.assertIn(source, checks.PUBLICATIONS)
        self.assertEqual(set(checks.SOURCES), set(checks.RUN_CADENCE_H))

    def test_the_a9_sources_are_all_known_here(self):
        import _publication_check  # noqa: PLC0415
        self.assertTrue(set(_publication_check.SOURCES) <= set(checks.SOURCES))
        for source, (table, _, key) in _publication_check.SOURCES.items():
            self.assertEqual(checks.PUBLICATIONS[source][0], table)
            self.assertEqual(checks.PUBLICATIONS[source][2], key)

    def test_every_constant_carries_its_source_line(self):
        text = open(checks.__file__, encoding="utf-8").read()
        for name in ("RUN_CADENCE_H", "PUBLICATION_INTERVAL_H", "COVERAGE"):
            block = text[text.index(name):]
            head = text[:text.index(name)]
            self.assertIn("probes/a28-backtest.md", head[-1500:] + block[:600],
                          "{} must say where its numbers were measured".format(name))
        self.assertIn("2026-09-15", text)

    def test_the_statements_bind_only_source_and_rewrite_for_psycopg2(self):
        for source in checks.SOURCES:
            for metric, sql in checks.statements_for(source).items():
                self.assertEqual(set(re.findall(r":([a-z_]+)", sql)) <= {"source"}, True, (metric, sql))
                self.assertNotIn(":", checks.pyformat(sql).replace("%(source)s", ""), metric)
        self.assertIn("%(source)s", checks.pyformat(checks.STATEMENTS["failed_24h"]))


class DagHelper(unittest.TestCase):
    def test_the_dag_helper_imports_without_airflow(self):
        import _value_check  # noqa: PLC0415
        self.assertEqual(_value_check.POSTGRES_CONNECTION, "upto_check_postgres")
        sql = _value_check._insert_sql()
        self.assertNotIn(":", sql.replace("%(", ""))
        self.assertIn("%(source)s", sql)
        self.assertIn("%(verdict)s", sql)

    def test_a_finding_composes_into_one_message_naming_source_and_hours(self):
        import _alerts  # noqa: PLC0415
        _, findings = checks.evaluate("gcis-restaurant-registry", values(hours_since_last_stored=1500.0))
        self.assertEqual(len(findings), 1)
        detail = "RuntimeError: " + "; ".join(f.sentence for f in findings)
        message = _alerts.compose_message("upto_business_status_ingest", "value_check", "manual__x", 3, 2, detail)
        self.assertIn("gcis-restaurant-registry", message)
        self.assertIn("1500.0 h", message)
        self.assertLessEqual(len(message), _alerts.MESSAGE_CAP)


if __name__ == "__main__":
    unittest.main()
