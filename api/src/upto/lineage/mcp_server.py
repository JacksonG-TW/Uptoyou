"""MVP item 14 — the lineage tool a model can query, over MCP on stdio.

Start it from the same compose stack, which is what ticket 09 asks for and needs no new service
and no second port:

    docker compose exec -T api python -m upto.lineage.mcp_server

**Hand-written JSON-RPC rather than the MCP SDK, and that is a real choice with a cost.** The
protocol surface this tool needs is three methods — `initialize`, `tools/list`, `tools/call` —
and the alternative is a dependency in the image whose own transitive set is larger than this
file. §6 rules out a component the builder cannot defend, and every line here is defensible by
reading it. **The cost is admitted:** a client using a part of MCP this does not implement gets
a clean `-32601`, and protocol drift is now this project's problem rather than a library's.
Nothing here is a reason to avoid the SDK later; it is a reason not to need it yet.

**H20 is why the tool list is short.** Every question the weight engine will make possible —
whose preference, which channel, why a place lost — is refused with a stated reason rather than
absent, because a tool that simply lacks the feature today gains it the day somebody finds it
useful. `explain_place_loss` exists **only** to refuse, and a test asserts the refusal.

**Nothing is computed and presented as recorded.** Every field in every answer is a stored
column or a count taken at query time, and the answers say which timestamps are detection
times (D42).
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime
from typing import Any, Callable, Dict

from . import queries

# `session_factory` is imported inside `_call`, not here. The protocol half of this file and
# H20's refusal are both reachable without a database, and "tested without a database" has to
# mean without the database libraries too — otherwise the tests only run where the stack does.

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "upto-lineage"
SERVER_VERSION = "0.1.0"

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


def _hour(value: str) -> datetime:
    """Parse an hour and refuse one without an offset.

    H17: a timestamp whose zone is unknown cannot be compared with anything here, and guessing
    the offset is the hazard rather than the inconvenience.
    """
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None:
        raise ValueError(
            "hour must carry a UTC offset, for example 2026-08-11T19:00:00+08:00 — a stamp "
            "without one cannot be compared with a stored reading (H17)"
        )
    return stamp


TOOLS: Dict[str, Dict[str, Any]] = {
    "forecast_reading_source": {
        "description": (
            "Where one forecast reading came from: every stored version of it, newest first, "
            "each with its publication, content hash, the run that wrote it, and the detection "
            "time. The forecast carries no publication time, so the stamp is when the ingest "
            "first saw the content and is labelled as such."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "township_code": {"type": "string", "description": "內政部 code, e.g. 63000040"},
                "hour": {"type": "string", "description": "the hour described, with an offset"},
                "element": {"type": "string", "description": "CWA element group, e.g. 溫度"},
                "measure": {"type": "string", "description": "the named measure, e.g. Temperature"},
            },
            "required": ["township_code", "hour", "element", "measure"],
        },
    },
    "explain_round": {
        "description": (
            "Recompute one round from its revealed seed and say whether the arithmetic agrees with "
            "what was stored (D108). Returns the commitment published at open, the seed revealed at "
            "close, whether sha256 of the DECODED seed equals that commitment, the deciding member "
            "id, every member's derived pair, and whether the pair stored on the round equals the "
            "pair the seed produces. Member ids only, never nicknames. An open round reveals no seed "
            "and says so. The seed is 32 bytes written as hex — decode before hashing. "
            "It also names the rain baseline (A12/D71): the reading every rain factor in the round "
            "was measured against, its township and probability, and whether every factor came from "
            "the same publication. That reading has no contribution row of its own — the driest "
            "township produces none (D43) — so without it a round's rain arithmetic could not be "
            "reconstructed from its own rows. `rain_baseline: null` means no comparison happened, "
            "which is not the same as a comparison that found no difference."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "round_id": {"type": "integer", "description": "the round to recompute"},
            },
            "required": ["round_id"],
        },
    },
    "observation_reading_source": {
        "description": (
            "Where one station observation came from: every stored version, its publication, "
            "content hash, the run that wrote it, the hour it describes and when it was "
            "retrieved."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "station_id": {"type": "string", "description": "CWA station id, e.g. C0AH70"},
                "hour": {"type": "string", "description": "ObsTime, with an offset"},
                "element": {"type": "string", "description": "e.g. AirTemperature"},
            },
            "required": ["station_id", "hour", "element"],
        },
    },
    "run_detail": {
        "description": (
            "What one ingest run did, including a run that wrote nothing. A no-change run is "
            "the ordinary outcome for the forecast — about twenty of twenty-four daily runs — "
            "and is answerable and described as such, distinct from a run that failed."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"run_id": {"type": "integer"}},
            "required": ["run_id"],
        },
    },
    "run_history": {
        "description": "Recent ingest runs, optionally for one source, newest first.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "e.g. F-D0047-061; omit for all"},
                "limit": {"type": "integer", "description": "default 20"},
            },
        },
    },
    "publication_detail": {
        "description": (
            "What one publication holds: its content hash, size, how many reading rows it "
            "carries and over how many townships or stations. The counts are queried, never "
            "remembered."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "dataset_id": {"type": "string", "description": "F-D0047-061 or O-A0001-001"},
                "publication_id": {"type": "integer"},
            },
            "required": ["dataset_id", "publication_id"],
        },
    },
    "explain_place_loss": {
        "description": (
            "REFUSES, by design. Why a place lost a roll runs through the weight channels, and "
            "the private channel carries a member and a reason its owner was promised nobody "
            "would see. This tool answers lineage over ingested rows only; the private channel "
            "is answerable in aggregate at most, and the weight engine does not exist yet. The "
            "tool is listed rather than omitted so the refusal is discoverable (H20)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"place": {"type": "string"}, "round_id": {"type": "integer"}},
        },
    },
}


async def _call(name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    if name == "explain_place_loss":
        # Refused before anything is opened: the boundary is structural, not a filter over
        # results, and this line is what makes that testable with no database present.
        queries.refuse("why a place lost a roll, or whose preference affected it")

    # Arguments are validated before a session is opened. An hour without an offset is a bad
    # request and has to read as one (H17) — parsed inside the session it surfaced as an
    # internal error instead, which tells a caller nothing about what to fix, and it could not
    # be tested without a database.
    hour = _hour(arguments["hour"]) if "hour" in arguments else None

    from ..db import session_factory

    async with session_factory()() as session:
        if name == "explain_round":
            answer = await queries.explain_round(session, arguments["round_id"])
        elif name == "forecast_reading_source":
            answer = await queries.forecast_reading_source(
                session,
                arguments["township_code"],
                hour,
                arguments["element"],
                arguments["measure"],
            )
        elif name == "observation_reading_source":
            answer = await queries.observation_reading_source(
                session, arguments["station_id"], hour, arguments["element"]
            )
        elif name == "run_detail":
            answer = await queries.run_detail(session, int(arguments["run_id"]))
        elif name == "run_history":
            answer = await queries.run_history(
                session, arguments.get("source"), int(arguments.get("limit", 20))
            )
        elif name == "publication_detail":
            answer = await queries.publication_detail(
                session, arguments["dataset_id"], int(arguments["publication_id"])
            )
        else:
            raise KeyError(name)

    return {
        "question": answer.question,
        "found": answer.found,
        "detail": answer.detail,
        "rows": answer.rows,
        "note": answer.note,
    }


def _result(request_id: Any, payload: Dict[str, Any]) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": payload}


def _error(request_id: Any, code: int, message: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _tool_text(payload: Dict[str, Any]) -> Dict[str, Any]:
    """MCP returns tool output as content blocks. JSON in a text block keeps it readable to a
    model and exact for a reader, which a prose summary would not be."""
    return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2)}]}


async def handle(message: Dict[str, Any]) -> Dict[str, Any] | None:
    if message.get("jsonrpc") != "2.0":
        return _error(message.get("id"), INVALID_REQUEST, "jsonrpc must be \"2.0\"")
    method = message.get("method")
    request_id = message.get("id")

    # A notification has no id and takes no reply — `notifications/initialized` is the one a
    # client sends after the handshake, and answering it is a protocol error.
    if request_id is None:
        return None

    if method == "initialize":
        return _result(
            request_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        )

    if method == "tools/list":
        return _result(
            request_id,
            {
                "tools": [
                    {"name": name, "description": spec["description"], "inputSchema": spec["inputSchema"]}
                    for name, spec in TOOLS.items()
                ]
            },
        )

    if method == "tools/call":
        params = message.get("params") or {}
        name = params.get("name")
        if name not in TOOLS:
            return _error(request_id, INVALID_PARAMS, "no tool named {!r}".format(name))
        try:
            payload = await _call(name, params.get("arguments") or {})
        except queries.LineageRefused as refused:
            # A refusal is an answer, not a transport failure. `isError` marks it so a model
            # does not read it as data, and the message says why rather than "not permitted".
            return _result(
                request_id,
                {"content": [{"type": "text", "text": str(refused)}], "isError": True},
            )
        except KeyError as missing:
            return _error(request_id, INVALID_PARAMS, "missing argument: {}".format(missing))
        except ValueError as bad:
            return _error(request_id, INVALID_PARAMS, str(bad))
        except Exception as failure:  # noqa: BLE001 — the transport must survive one bad call
            return _error(request_id, INTERNAL_ERROR, "{}: {}".format(type(failure).__name__, failure))
        return _result(request_id, _tool_text(payload))

    return _error(request_id, METHOD_NOT_FOUND, "unsupported method {!r}".format(method))


async def serve(reader: Callable[[], str] | None = None, writer=None) -> int:
    """One JSON object per line, in and out.

    Line-delimited rather than the LSP-style `Content-Length` framing: it is what MCP's stdio
    transport specifies, and it is what makes this file testable by handing it a list of lines.
    """
    read_line = reader or sys.stdin.readline
    out = writer or sys.stdout
    while True:
        line = read_line()
        if not line:
            return 0
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            out.write(json.dumps(_error(None, PARSE_ERROR, "not JSON")) + "\n")
            out.flush()
            continue
        reply = await handle(message)
        if reply is not None:
            out.write(json.dumps(reply, ensure_ascii=False) + "\n")
            out.flush()


def main() -> int:
    return asyncio.run(serve())


if __name__ == "__main__":
    sys.exit(main())
