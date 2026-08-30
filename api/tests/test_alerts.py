#!/usr/bin/env python3
"""A10's failure alert — what may leave this machine, and what the message says.

Run: python3 app/api/tests/test_alerts.py    (no network, no database, no Airflow)

**The tests worth reading are the redaction ones.** This is the only code path in the repository
that sends text off the machine, and it runs exactly when something has already gone wrong and
nobody is watching. `_database_url()` builds `postgresql+asyncpg://user:PASSWORD@db:5432/…` and a
driver puts that string in its exception, so an unredacted forward would post `POSTGRES_PASSWORD`
into a chat. Everything else here is formatting.
"""

import ast
import os
import sys
import unittest

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "airflow", "dags"))

import _alerts as alerts  # noqa: E402


class NoCredentialLeavesThisMachine(unittest.TestCase):
    def test_a_database_url_loses_its_password(self):
        leaked = "could not connect: postgresql+asyncpg://upto:hunter2pw@db:5432/upto"
        cleaned = alerts.scrub(leaked)
        self.assertNotIn("hunter2pw", cleaned)
        self.assertIn("postgresql+asyncpg://***:***@db:5432/upto", cleaned)

    def test_the_user_goes_too_not_only_the_password(self):
        """A login is not a secret and it is still an identity worth not broadcasting; the pattern
        replaces the whole userinfo because splitting it buys nothing."""
        self.assertNotIn("upto", alerts.scrub("postgresql://upto:pw@db/upto").split("@")[0])

    def test_a_named_environment_secret_is_removed_wherever_it_appears(self):
        """The case the URL pattern cannot catch: a password interpolated into prose."""
        original = os.environ.get("POSTGRES_PASSWORD")
        os.environ["POSTGRES_PASSWORD"] = "correcthorse"
        try:
            cleaned = alerts.scrub("authentication failed for password correcthorse (twice)")
            self.assertNotIn("correcthorse", cleaned)
            self.assertEqual(cleaned.count(alerts.REDACTED), 1)
        finally:
            if original is None:
                del os.environ["POSTGRES_PASSWORD"]
            else:
                os.environ["POSTGRES_PASSWORD"] = original

    def test_the_bot_token_itself_is_removed(self):
        """It is the transport's own credential, and the transport is where it must never appear.

        **The stand-in is assembled rather than written out**, because `tools/secret_scan.py`
        refuses a credential-shaped literal assigned to a name like `token` — and it is right to:
        the gate cannot tell a fake from a real one, and not being able to is the property that
        makes it worth having. Caught by the gate on the first attempt to commit this file.
        """
        stand_in = "1234567" + "89:" + "A" * 35
        self.assertNotIn(stand_in, alerts.scrub("posting to bot" + stand_in, extra=(stand_in,)))

    def test_a_longer_secret_is_scrubbed_before_a_shorter_one_it_contains(self):
        """Shortest-first would carve the longer value into fragments that then never match, so the
        longer secret would survive in pieces. The order is not cosmetic."""
        cleaned = alerts.scrub("abcdefgh and abcd", extra=("abcd", "abcdefgh"))
        self.assertNotIn("abcdefgh", cleaned)

    def test_a_short_value_is_not_treated_as_a_secret(self):
        """An environment variable set to `db` or `up` would otherwise redact every occurrence of
        those letters and turn every message into asterisks."""
        self.assertEqual(alerts.scrub("the db is down", extra=("db",)), "the db is down")

    def test_scrubbing_nothing_returns_a_string_and_not_none(self):
        self.assertEqual(alerts.scrub(""), "")

    def test_an_ordinary_failure_sentence_survives_intact(self):
        """The reason redaction is not «send nothing»: this sentence is the whole value of the
        alert, and it must arrive unchanged."""
        sentence = ("fia-business-tax: the row count collapsed: 12 rows against the previous "
                    "publication's 14513, down 99.9%")
        self.assertEqual(alerts.scrub(sentence), sentence)


class TheMessageSaysWhatAPhoneNeedsFirst(unittest.TestCase):
    def message(self, **overrides):
        arguments = {
            "dag_id": "upto_business_tax_ingest",
            "task_id": "check_publication",
            "run_id": "scheduled__2026-08-19T20:20:00+00:00",
            "try_number": 3,
            "max_tries": 2,
            "detail": "RuntimeError: the row count collapsed",
            "log_path": "/opt/airflow/logs/x/attempt=3.log",
        }
        arguments.update(overrides)
        return alerts.compose_message(**arguments)

    def test_the_first_line_carries_the_dag_the_task_and_the_word_failed(self):
        """A notification shows one line. It has to be the one that says what broke."""
        first = self.message().split("\n")[0]
        self.assertIn("upto_business_tax_ingest", first)
        self.assertIn("check_publication", first)
        self.assertIn("FAILED", first)

    def test_the_attempt_count_reads_as_attempts_and_not_as_retries(self):
        """`max_tries` is the number of RETRIES, so 2 means three attempts. Printing it as the total
        gave «attempt 3 of 2», which reads as a bug in the alert instead of the last attempt."""
        self.assertIn("attempt 3 of 3", self.message())

    def test_no_max_tries_still_names_the_attempt(self):
        self.assertIn("attempt 1", self.message(try_number=1, max_tries=0))

    def test_the_run_id_and_the_log_path_are_both_there(self):
        body = self.message()
        self.assertIn("scheduled__2026-08-19T20:20:00+00:00", body)
        self.assertIn("/opt/airflow/logs/x/attempt=3.log", body)

    def test_the_log_pointer_is_a_path_and_never_a_url(self):
        """The UI is on `localhost:8081`, unreachable from the phone this arrives on — a link would
        be a dead end dressed as an answer."""
        self.assertNotIn("http", self.message())

    def test_a_long_detail_is_clipped_and_says_it_was(self):
        body = self.message(detail="x" * 5000)
        self.assertLessEqual(len(body), alerts.MESSAGE_CAP)
        self.assertIn("…", body)

    def test_a_missing_detail_still_composes(self):
        """A failure with no exception in the context — the alert must still say which task."""
        body = self.message(detail="")
        self.assertIn("check_publication", body)
        self.assertIn("FAILED", body)


class TheCallbackNeverRaises(unittest.TestCase):
    """One red task must not become two, and the second would say nothing about the pipeline."""

    def test_a_context_with_nothing_in_it_is_survived(self):
        alerts.send_failure_alert({})

    def test_a_context_that_raises_when_read_is_survived(self):
        class Hostile(dict):
            def get(self, *args, **kwargs):
                raise ValueError("no")

        alerts.send_failure_alert(Hostile())

    def test_not_a_mapping_at_all_is_survived(self):
        alerts.send_failure_alert(None)


class TheSelfTestIsTheOneDagAllowedToFail(unittest.TestCase):
    """A10's self-test (owner-ruled 2026-08-19) proves the one thing the rest of A10's verification
    could not: that Airflow *calls* the callback on a real failure. Three properties of it are
    load-bearing and each would be easy to lose in a tidy-up."""

    def source(self):
        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(here, "..", "..", "airflow", "dags", "alert_selftest.py")
        return open(path, encoding="utf-8").read()

    def test_it_has_no_schedule(self):
        """A DAG that fails on a timer is a channel that cries wolf nightly, and a channel that cries
        wolf nightly stops being read — which would cost more than the gap it closes."""
        self.assertIn("schedule=None", self.source())

    def test_it_arrives_paused(self):
        """Everywhere else in this repository paused-on-arrival is the standing hazard; here it is the
        intent, so it is stated rather than inherited."""
        self.assertIn("is_paused_upon_creation=True", self.source())

    def test_it_does_not_retry(self):
        """`on_failure_callback` fires only once the retries are spent, so this repository's usual
        `retries: 2` with a ten-minute delay would make a self-test take twenty minutes to send one
        message. The number is the difference between a usable test and an abandoned one."""
        self.assertIn('"retries": 0', self.source())

    def test_the_message_says_nothing_is_wrong(self):
        """It is what arrives on the phone and what stands in the log. The reader of an alert at 03:20
        has not opened the file and must not need to."""
        self.assertIn("nothing is wrong", self.source())

    def test_it_writes_nothing_and_fetches_nothing(self):
        """The reason this DAG exists rather than a broken Connection: no source, no ledger row, no
        side effect. A false `failed` row in `ingest_run` would be a lie in the one table whose job is
        telling a broken source from a quiet one.

        **This reads the AST, and the first version read the text — which failed on its own docstring.**
        Forbidding the substring `ingest` matched the sentence *explaining why* no ingest happens. That
        is H44's shape exactly: a guard over source has to read the code, not the prose around it.
        """
        tree = ast.parse(self.source())
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                names.update(alias.name.split(".")[0] for alias in node.names)
                if isinstance(node, ast.ImportFrom) and node.module:
                    names.add(node.module.split(".")[0])
        for forbidden in ("PostgresHook", "subprocess", "urllib", "socket", "requests"):
            self.assertNotIn(forbidden, names)
        # And nothing from the ingest package, by any spelling the code could reach it with.
        self.assertFalse([n for n in names if "ingest" in n.lower()], sorted(names))


class TheConnectionShapeIsFixed(unittest.TestCase):
    def test_the_connection_id_matches_what_init_sh_creates(self):
        """Two files have to agree on one string, so the test reads the shell rather than trusting
        that they do."""
        here = os.path.dirname(os.path.abspath(__file__))
        init = open(os.path.join(here, "..", "..", "airflow", "init.sh"), encoding="utf-8").read()
        self.assertIn("airflow connections add {}".format(alerts.CONNECTION_ID), init)
        self.assertIn("airflow connections delete {}".format(alerts.CONNECTION_ID), init)

    def test_init_sh_creates_the_connection_only_when_both_values_are_present(self):
        """Absent is legal — a fresh clone and the split-boot stack have no bot. If this guard is
        ever removed, `airflow-init` fails and the whole stack stops standing up."""
        here = os.path.dirname(os.path.abspath(__file__))
        init = open(os.path.join(here, "..", "..", "airflow", "init.sh"), encoding="utf-8").read()
        self.assertIn('if [[ -n "${UPTO_TELEGRAM_BOT_TOKEN:-}"', init)
        self.assertIn('-n "${UPTO_TELEGRAM_CHAT_ID:-}" ]]', init)

    def test_the_env_names_are_listed_in_env_example_and_no_value_is(self):
        here = os.path.dirname(os.path.abspath(__file__))
        example = open(os.path.join(here, "..", "..", ".env.example"), encoding="utf-8").read()
        self.assertIn("UPTO_TELEGRAM_BOT_TOKEN=\n", example)
        self.assertIn("UPTO_TELEGRAM_CHAT_ID=\n", example)


class EveryDagIsWired(unittest.TestCase):
    """A callback on four of five DAGs is worse than none: the one that is silent is the one you
    learn to trust."""

    def test_every_dag_file_sets_the_callback(self):
        """**The count is asserted so that adding a DAG has to come here**, which is the whole
        anti-rot value: it went 5 -> 6 when `alert_selftest.py` landed and this test is what said so.
        A new DAG file with no callback would otherwise be silently unalerted, and the DAG that is
        silent is the one you learn to trust."""
        here = os.path.dirname(os.path.abspath(__file__))
        dags = os.path.join(here, "..", "..", "airflow", "dags")
        files = [name for name in sorted(os.listdir(dags))
                 if name.endswith(".py") and not name.startswith("_")]
        # 8 since 2026-08-30: `db_backup.py` joined (A22's nightly dump). It was 7 from
        # 2026-08-28, when `weather_retention.py` landed (D42's ninety-day window).
        self.assertEqual(len(files), 8, files)
        for name in files:
            source = open(os.path.join(dags, name), encoding="utf-8").read()
            # **The import is read from the AST, not matched as a string.** The first version of this
            # asserted the exact line `from _alerts import send_failure_alert` and went red on
            # `alert_selftest.py`, which imports `CONNECTION_ID` alongside it — a true file failing a
            # test about a spelling. What matters is that the name arrives from that module.
            imported = set()
            for node in ast.walk(ast.parse(source)):
                if isinstance(node, ast.ImportFrom) and node.module == "_alerts":
                    imported.update(alias.name for alias in node.names)
            self.assertIn("send_failure_alert", imported, name)
            self.assertIn('"on_failure_callback": send_failure_alert', source, name)

    def test_every_dag_file_that_imports_a_sibling_inserts_the_path_first(self):
        """H46 — Airflow 3 does not put the dags folder on `sys.path`, and a DAG that fails to
        import keeps showing its previous serialisation in `airflow dags list`."""
        here = os.path.dirname(os.path.abspath(__file__))
        dags = os.path.join(here, "..", "..", "airflow", "dags")
        for name in sorted(os.listdir(dags)):
            if not name.endswith(".py") or name.startswith("_"):
                continue
            source = open(os.path.join(dags, name), encoding="utf-8").read()
            insert = source.find("sys.path.insert")
            first_sibling = min(
                (source.find(line) for line in ("from _alerts", "from _publication_check")
                 if source.find(line) != -1), default=-1)
            self.assertNotEqual(insert, -1, name)
            self.assertLess(insert, first_sibling, name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
