#!/usr/bin/env python3
"""Item 14's lineage tool: the protocol, and the boundary H20 names.

Run: python3 app/api/tests/test_lineage_mcp.py

No network and no database. The protocol half is exercised by handing the server a list of
lines, which is the reason `serve()` takes a reader rather than reading `sys.stdin` directly.
The boundary half needs no database at all, which is the point: **the refusal is structural, so
it can be asserted without any data existing.**

**The test H20 asks for is `RefusesTheForbiddenQuestion`.** The hazard is that the tool is built
to be useful and the most useful answer is the complete one, so what has to be proven is that
the direct question is refused — not that nobody has asked it yet.
"""

import asyncio
import io
import json
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from upto.lineage import mcp_server as server  # noqa: E402
from upto.lineage import queries  # noqa: E402


def exchange(*messages):
    """Feed the server some lines and collect what it wrote back."""
    lines = [json.dumps(m) + "\n" for m in messages]
    lines.append("")
    out = io.StringIO()
    asyncio.run(server.serve(reader=lambda: lines.pop(0), writer=out))
    return [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]


class Handshake(unittest.TestCase):
    def test_initialize_answers_with_a_protocol_version(self):
        replies = exchange({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        self.assertEqual(len(replies), 1)
        result = replies[0]["result"]
        self.assertEqual(result["protocolVersion"], server.PROTOCOL_VERSION)
        self.assertEqual(result["serverInfo"]["name"], "upto-lineage")
        self.assertIn("tools", result["capabilities"])

    def test_a_notification_gets_no_reply(self):
        """`notifications/initialized` has no id, and answering it is a protocol error."""
        replies = exchange({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.assertEqual(replies, [])

    def test_unknown_method_is_method_not_found(self):
        replies = exchange({"jsonrpc": "2.0", "id": 9, "method": "resources/list"})
        self.assertEqual(replies[0]["error"]["code"], server.METHOD_NOT_FOUND)

    def test_bad_json_does_not_kill_the_transport(self):
        lines = ["not json\n", json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}) + "\n", ""]
        out = io.StringIO()
        asyncio.run(server.serve(reader=lambda: lines.pop(0), writer=out))
        replies = [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]
        self.assertEqual(replies[0]["error"]["code"], server.PARSE_ERROR)
        self.assertIn("tools", replies[1]["result"], "the second message must still be served")

    def test_missing_jsonrpc_version_is_an_invalid_request(self):
        replies = exchange({"id": 1, "method": "initialize"})
        self.assertEqual(replies[0]["error"]["code"], server.INVALID_REQUEST)


class ToolList(unittest.TestCase):
    def test_every_tool_declares_a_schema_and_a_description(self):
        replies = exchange({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        tools = replies[0]["result"]["tools"]
        self.assertTrue(tools)
        for tool in tools:
            self.assertTrue(tool["description"].strip(), tool["name"])
            self.assertEqual(tool["inputSchema"]["type"], "object", tool["name"])

    def test_a_run_that_wrote_nothing_is_advertised_as_answerable(self):
        """Ticket 09: a no-change run is lineage worth pointing at, not an absence — so the
        tool has to say it answers about one, or a model will not ask."""
        description = server.TOOLS["run_detail"]["description"]
        self.assertIn("wrote nothing", description)
        self.assertIn("no-change", description)

    def test_the_refusing_tool_is_listed_rather_than_omitted(self):
        """H20: a tool that merely lacks the feature gains it the day somebody wants it. Listed,
        the refusal is discoverable and the reason travels with it."""
        replies = exchange({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        names = [tool["name"] for tool in replies[0]["result"]["tools"]]
        self.assertIn("explain_place_loss", names)

    def test_calling_an_unknown_tool_is_invalid_params(self):
        replies = exchange(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "nope"}}
        )
        self.assertEqual(replies[0]["error"]["code"], server.INVALID_PARAMS)


class RefusesTheForbiddenQuestion(unittest.TestCase):
    """H20's own test: ask the most direct question available and assert what is not in the answer."""

    def setUp(self):
        replies = exchange(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "explain_place_loss",
                    "arguments": {"place": "某某餐廳", "round_id": 1},
                },
            }
        )
        self.result = replies[0]["result"]
        self.text = self.result["content"][0]["text"]

    def test_it_is_marked_as_an_error_not_as_data(self):
        self.assertTrue(self.result.get("isError"), "a model must not read the refusal as an answer")

    def test_no_member_and_no_reason_appear_in_the_answer(self):
        """The assertion H20 words: nothing about the people at the table.

        Naming the *category* it will not answer is not a leak — it is the refusal being
        specific, and an earlier version of this test failed on the word `preference` appearing
        in the sentence "whose preference affected it". What must be absent is an identifier or
        a stored reason, so the assertions are about those.
        """
        for leak in ("member_id", "principal_id", "nickname", "weight_contribution", "effect="):
            self.assertNotIn(leak, self.text)
        self.assertEqual(self.result["content"][0]["type"], "text")
        self.assertNotIn("rows", self.result, "a refusal carries no data payload")

    def test_the_refusal_names_what_it_will_not_answer(self):
        """The opposite property, and it is the one that makes the refusal useful: a model told
        only "not permitted" asks again a different way."""
        self.assertIn("private", self.text)
        self.assertIn("whose", self.text)

    def test_the_refusal_says_why_rather_than_not_permitted(self):
        self.assertIn("aggregate", self.text)
        self.assertIn("H20", self.text)

    def test_the_refusal_is_reachable_without_a_database(self):
        """Structural, not a filter over query results: no session was opened to produce it."""
        with self.assertRaises(queries.LineageRefused):
            queries.refuse("whose preference affected it")


class BoundaryIsStructural(unittest.TestCase):
    def test_no_query_mentions_a_members_private_facts(self):
        """The narrowness is the mitigation. If a query ever names one of these, the reviewer who
        added it has stepped over H20 without noticing, and this fails.

        **The list is read from `queries.FORBIDDEN_SUBJECTS`, not copied.** It used to be typed here as
        well, and when H20 was narrowed for `explain_round` (D108, `06c9f9f`) the constant moved and
        this copy did not — so the test failed on a query the ruling had just permitted, which is a
        test disagreeing with the decision it is supposed to enforce. One source, so a narrowing lands
        in one place.

        `principal` stays hard-coded beside it, because that one was **not** narrowed and never should
        be: a principal is the identity behind a seat and no surface has ever had a reason to see it
        (H19). Keeping it here rather than in the constant says out loud that it is not up for the same
        negotiation.
        """
        forbidden = tuple(subject.replace(" ", "_") for subject in queries.FORBIDDEN_SUBJECTS)
        for statement in self.statements():
            lowered = statement.lower()
            for subject in forbidden + ("principal",):
                self.assertNotIn(subject, lowered, statement[:80])

    def test_only_the_declared_tables_are_read(self):
        """Scanned over the SQL statements alone. Scanning the whole file caught `from sqlalchemy
        import text` as a table named sqlalchemy, which is a test failing for its own reasons."""
        statements = self.statements()
        referenced = set()
        for statement in statements:
            referenced |= set(re.findall(r"(?:from|join)\s+([a-z_]+)", statement, re.IGNORECASE))
        unexpected = referenced - queries.READABLE_TABLES
        self.assertEqual(unexpected, set(), "a table outside the declared set is being read")

    def statements(self):
        """**Every SQL string in the module, found by parsing it — not by matching one style.**

        *Rewritten 2026-08-19, after the previous version failed to see a query that read two
        forbidden tables.* It matched triple-quoted blocks at module level, which is how every query in this
        file happened to be written. A new query written as an inline `text("select …")` inside a
        function was **completely invisible to it**, and `test_only_the_declared_tables_are_read`
        passed while `round` and `member` were being read — `member` being one of H20's named
        forbidden subjects.

        So the boundary was not enforced; it was enforced *for one coding style*, which is the same
        as not being enforced, because nobody writing the next query knows what the style was for.

        An AST walk over every string constant sees them all regardless of quoting, nesting or
        indentation. It cannot see SQL assembled from fragments at run time — that would defeat any
        static check — so `test_no_sql_is_built_by_concatenation` closes the remaining route rather
        than leaving it as the next silent gap.
        """
        import ast

        source = open(queries.__file__, encoding="utf-8").read()
        found = []
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                text_value = node.value.strip()
                if re.match(r"select\b", text_value, re.IGNORECASE):
                    found.append(text_value)
        self.assertTrue(found, "no SQL found — this test would silently pass")
        return found

    def test_no_sql_is_built_by_concatenation(self):
        """A static scan can only read literals, so the module may not assemble SQL from pieces.

        Without this, the AST walk above is bypassable by exactly the trick it was written to stop:
        `text("select … from " + table)` puts the table name outside every literal. The rule is
        therefore *no `select` literal is ever adjacent to a `+` or an f-string*, which is stricter
        than necessary and is the kind of strictness a boundary should have.
        """
        import ast

        source = open(queries.__file__, encoding="utf-8").read()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.JoinedStr):   # an f-string
                rendered = "".join(
                    part.value for part in node.values if isinstance(part, ast.Constant)
                )
                self.assertNotRegex(
                    rendered.strip(), r"(?i)^select\b",
                    "SQL built as an f-string cannot be checked against READABLE_TABLES")
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
                for side in (node.left, node.right):
                    if isinstance(side, ast.Constant) and isinstance(side.value, str):
                        self.assertNotRegex(
                            side.value.strip(), r"(?i)^select\b",
                            "SQL built by concatenation cannot be checked against READABLE_TABLES")


class HourMustCarryAZone(unittest.TestCase):
    def test_a_naive_hour_is_refused(self):
        """H17: guessing the offset is the hazard, not the inconvenience."""
        with self.assertRaises(ValueError):
            server._hour("2026-08-11T19:00:00")

    def test_an_hour_with_an_offset_parses(self):
        self.assertIsNotNone(server._hour("2026-08-11T19:00:00+08:00").tzinfo)

    def test_the_naive_hour_reaches_the_client_as_invalid_params(self):
        replies = exchange(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "observation_reading_source",
                    "arguments": {
                        "station_id": "C0AH70",
                        "hour": "2026-08-11T19:00:00",
                        "element": "AirTemperature",
                    },
                },
            }
        )
        self.assertEqual(replies[0]["error"]["code"], server.INVALID_PARAMS)
        self.assertIn("offset", replies[0]["error"]["message"])


class TimeLabels(unittest.TestCase):
    def test_a_forecast_stamp_is_a_detection_time(self):
        """D42: CWA never says when a forecast was published, so the label is part of the answer."""
        self.assertEqual(queries._time_label(queries.FORECAST_DATASET), "detected_at")

    def test_an_observation_stamp_is_a_retrieval_time(self):
        self.assertEqual(queries._time_label(queries.OBSERVATION_DATASET), "retrieved_at")


class TheRainBaselineIsNameable(unittest.TestCase):
    """A12 / RR-8 — the reading a round's rain factors were measured against.

    D71 is relative: a place's factor is `1 − gap/120` against the pool's lowest 降雨機率, and the
    place standing on that lowest reading produces **no contribution at all** (D43). So the number
    every factor is a gap from is recorded nowhere a contribution can point at, and without
    revision 0030 a round's rain arithmetic could not be reconstructed from its own rows.
    """

    def test_explain_round_says_it_names_the_baseline(self):
        described = server.TOOLS["explain_round"]["description"]
        self.assertIn("rain baseline", described)
        self.assertIn("rain_baseline: null", described,
                      "the absent case must be described, or null reads as zero")

    def test_the_baseline_table_is_declared_readable(self):
        self.assertIn("round_forecast_baseline", queries.READABLE_TABLES)

    def test_the_value_is_joined_and_not_copied(self):
        """D28: nothing derived is stored. The probability lives in the publication, and the
        composite FK is what guarantees it is still there to read — so the query joins for it."""
        self.assertIn("forecast_reading", queries.ROUND_BASELINE)
        self.assertIn("r.value as probability", queries.ROUND_BASELINE)

    def test_the_factors_themselves_are_not_read_here(self):
        """**The boundary said this before the author did.** Reporting the factors beside the
        baseline meant selecting from `weight_contribution`, and both structural guards fired: the
        table is outside `READABLE_TABLES` and `reason` is a forbidden subject. A filter to
        `contributor = 'weather'` narrows the rows without narrowing the reach, which is exactly
        what a structural guard exists to refuse."""
        self.assertNotIn("weight_contribution", queries.ROUND_BASELINE)
        self.assertNotIn("weight_contribution", " ".join(
            value for name, value in vars(queries).items()
            if isinstance(value, str) and name.isupper()
        ))


class OneBadCallNeverCostsTheReply(unittest.TestCase):
    """A tool whose answer cannot be encoded must come back as an ERROR, never as silence.

    **Measured, not imagined (2026-08-27).** `explain_round`'s new baseline row carried a raw
    `datetime`; `_tool_text` calls `json.dumps`, and that call sat *outside* the handler that claims
    "the transport must survive one bad call". So the process printed a traceback and sent **no
    reply at all** for that request id — the evaluator's client had nothing to read and simply
    waited. An error a caller can read is strictly better than silence, and this is the test that
    keeps the claim honest.
    """

    def dispatch(self, payload):
        original = server._call

        async def stub(name, arguments):
            return payload

        server._call = stub
        try:
            return asyncio.run(server.handle({
                "jsonrpc": "2.0", "id": 7, "method": "tools/call",
                "params": {"name": "run_history", "arguments": {}},
            }))
        finally:
            server._call = original

    def test_an_unencodable_answer_becomes_an_error_with_its_id(self):
        from datetime import datetime, timezone  # noqa: PLC0415

        reply = self.dispatch({"rows": [{"when": datetime(2026, 8, 27, tzinfo=timezone.utc)}]})
        self.assertIsNotNone(reply, "no reply is the failure this test exists for")
        self.assertEqual(reply["id"], 7)
        self.assertEqual(reply["error"]["code"], server.INTERNAL_ERROR)
        self.assertIn("TypeError", reply["error"]["message"])

    def test_an_encodable_answer_still_comes_back_as_a_result(self):
        """The guard must not turn every answer into an error — the boring half, asserted."""
        reply = self.dispatch({"rows": [{"when": "2026-08-27T00:00:00+00:00"}]})
        self.assertIn("result", reply)
        self.assertNotIn("error", reply)


if __name__ == "__main__":
    unittest.main(verbosity=2)
