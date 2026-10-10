"""The status table (`upto/statuses.py`) against the routes' own code (owner 「A」, 2026-10-10).

Host-side, no database: every status a route can return is derived from its source. That covers
the decorator's success code, `response.status_code = …`, `Response(status_code=…)`, and every
`HTTPException` in the route or in any project function it calls (aliases followed). The table and
that derivation must agree both ways:
- a status the code can return and the table lacks fails, so the front end's mapper never meets an
  unlisted status;
- a row the code can no longer return fails, so the table never promises a stale sentence.

Run: python3 app/api/tests/test_statuses.py
"""

import ast
import json
import os
import pathlib
import re
import sys
import unittest

SRC = pathlib.Path(__file__).resolve().parent.parent / "src" / "upto"
sys.path.insert(0, str(SRC.parent))

from upto import statuses  # noqa: E402


def _status_value(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    if isinstance(node, ast.Attribute):   # fastapi.status.HTTP_503_SERVICE_UNAVAILABLE
        found = re.match(r"HTTP_(\d{3})_", node.attr)
        if found:
            return int(found.group(1))
    raise AssertionError("a status that is not a literal: {}".format(ast.unparse(node)))


def derive():
    """{(method, path): {(status, detail or None)}} from the source."""
    functions, aliases, routes = {}, {}, []
    for path in sorted(SRC.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        prefix = ""
        for node in ast.walk(tree):
            if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
                    and getattr(node.value.func, "id", "") == "APIRouter"):
                prefix = next((k.value.value for k in node.value.keywords if k.arg == "prefix"), "")
        for node in tree.body:
            if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Name)
                    and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)):
                aliases[node.targets[0].id] = node.value.id
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions.setdefault(node.name, []).append(node)
                for decorator in node.decorator_list:
                    if (isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute)
                            and decorator.func.attr in ("get", "post", "delete", "put", "patch")):
                        success = next((_status_value(k.value) for k in decorator.keywords
                                        if k.arg == "status_code"), 200)
                        routes.append((decorator.func.attr.upper(), prefix + decorator.args[0].value,
                                       success, node))

    def returns(function, seen):
        found = set()
        for node in ast.walk(function):
            if (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Attribute)
                    and node.targets[0].attr == "status_code"):
                found.add((_status_value(node.value), None))
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name in ("HTTPException", "Response"):
                status = next((k.value for k in node.keywords if k.arg == "status_code"),
                              node.args[0] if node.args else None)
                if status is None:
                    continue
                detail = next((k.value for k in node.keywords if k.arg == "detail"),
                              node.args[1] if len(node.args) > 1 else None)
                literal = detail.value if (isinstance(detail, ast.Constant)
                                           and isinstance(detail.value, str)) else None
                found.add((_status_value(status), literal))
                continue
            name = aliases.get(name, name)
            if name in functions and name not in seen:
                for callee in functions[name]:
                    found |= returns(callee, seen | {name})
        return found

    derived = {}
    for method, path, success, function in routes:
        derived[(method, path)] = {(success, None)} | returns(function, {function.name})
    return derived


def table():
    rows = {}
    for row in statuses.STATUSES:
        if row["path"] == "*":
            continue
        rows.setdefault((row["method"], row["path"]), set()).add((row["status"], row["detail"]))
    return rows


class TheTableMatchesTheRoutes(unittest.TestCase):
    def setUp(self):
        self.code, self.rows = derive(), table()

    def test_the_derivation_found_the_routes(self):
        """A derivation that finds nothing passes every comparison, so it must find them."""
        self.assertGreaterEqual(len(self.code), 20, sorted(self.code))   # 23 on 2026-10-10

    def test_every_route_has_rows_and_every_row_a_route(self):
        self.assertEqual(sorted(set(self.code) - set(self.rows)), [], "routes with no rows")
        self.assertEqual(sorted(set(self.rows) - set(self.code)), [], "rows for no route")

    def test_every_status_a_route_can_return_is_listed_and_no_other(self):
        for route, found in sorted(self.code.items()):
            with self.subTest(route=route):
                self.assertEqual(sorted({s for s, _ in found}),
                                 sorted({s for s, _ in self.rows.get(route, set())}))

    def test_every_sentence_a_route_sends_is_its_row_and_no_row_is_stale(self):
        for route, found in sorted(self.code.items()):
            with self.subTest(route=route):
                sent = {(s, d) for s, d in found if d is not None}
                listed = {(s, d) for s, d in self.rows.get(route, set()) if d is not None}
                self.assertEqual(sorted(sent), sorted(listed))

    def test_a_status_with_a_built_sentence_has_a_row_without_one(self):
        """`detail` is None in the table exactly where the code builds the sentence at run time."""
        for route, found in sorted(self.code.items()):
            for status, detail in found:
                if detail is None:
                    with self.subTest(route=route, status=status):
                        self.assertIn((status, None), self.rows[route])


class TheScreensReadTheSameTable(unittest.TestCase):
    def test_the_json_is_this_table(self):
        """The screens read `web/src/lib/statuses.json`; a table edit without its export would leave
        the two disagreeing about what a status means."""
        exported = SRC.parent.parent.parent / "web" / "src" / "lib" / "statuses.json"
        if not exported.is_file():
            self.skipTest("no web/ beside this API (the tests image carries only api/)")
        held = json.loads(exported.read_text(encoding="utf-8"))
        self.assertEqual(held, {"actions": list(statuses.ACTIONS), "statuses": statuses.STATUSES},
                         "statuses.json is not the table: re-export it with the table edit")


class TheTableIsConsistent(unittest.TestCase):
    def test_every_action_is_one_the_front_end_knows(self):
        for row in statuses.STATUSES:
            self.assertIn(row["client_action"], statuses.ACTIONS, row)

    def test_the_void_is_410_everywhere(self):
        """Owner 「A」 2026-10-10: one status for the void, so it can never read as 409's conflict."""
        for row in statuses.STATUSES:
            if row["detail"] == statuses.VOID or row["client_action"] == "void":
                self.assertEqual((row["status"], row["client_action"], row["detail"]),
                                 (410, "void", statuses.VOID), row)

    def test_a_missing_seat_is_forget_seat_and_shows_no_detail(self):
        for row in statuses.STATUSES:
            if row["status"] == 401:
                self.assertEqual(row["client_action"], "forget_seat", row)

    def test_every_success_status_is_success(self):
        for row in statuses.STATUSES:
            if 200 <= row["status"] < 300:
                self.assertEqual(row["client_action"], "success", row)


if __name__ == "__main__":
    if os.environ.get("UPTO_STATUSES_PRINT"):
        for route, found in sorted(derive().items()):
            print(route, sorted(found, key=str))
    unittest.main(verbosity=1)
