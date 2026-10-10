"""Every status every route returns, what it means, and what a screen does with it (owner 「A», 2026-10-10).

Agreed with the front end before it was written: one row per (method, path, status, detail).
- `path` is the router's template as this API serves it. The proxy adds `/api` in front.
- `detail` is the exact sentence the response carries, or None where it is built at run time or is
  not for a person to read.
- `client_action` is the one thing a screen does:
  - `success`;
  - `show_detail`: show the API's sentence;
  - `reread`: the state moved, so read it again;
  - `retry_later`;
  - `forget_seat`: this key no longer holds a seat here, so drop it, and the screen speaks, never
    the detail;
  - `void`: the round is void, so drop it, show the sentence and offer a new round.

**The void is 410 on every round route** (propose, submit, take back, result, trip): gone for good,
never «conflict, try again», which is what 409 means everywhere else here.

`web/src/lib/statuses.json` is this table, exported for the screens. `tests/test_statuses.py` fails
when the JSON is not this table, and when this table and the routes' own code disagree; it derives
every status each route can return from that code. Pure data, so it imports anywhere.
"""

from __future__ import annotations

ACTIONS = ("success", "show_detail", "reread", "retry_later", "forget_seat", "void")

VOID = "這一輪作廢了：開始時在場的人都離開了。開新的一輪吧。"
NO_BEARER = "a bearer token is required (D67)"
NOT_A_MEMBER = "the token does not resolve to a member of this circle"
NAME_TOO_LONG = "圈子名稱太長了，最多80個字。一個表情符號可能算好幾個字。"
NICK_TOO_LONG = "暱稱太長了，最多40個字。一個表情符號可能算好幾個字。"
ALREADY_SUBMITTED = "你已經提交了。要改清單，先收回提交。"
NO_ROUND = "找不到這一輪。"


def _row(method, path, status, action, meaning, detail=None):
    assert action in ACTIONS, action
    return {"method": method, "path": path, "status": status, "meaning": meaning,
            "detail": detail, "client_action": action}


def _seat(method, path):
    """The two 401s every member route answers: no key, or a key with no seat in this circle."""
    return [
        _row(method, path, 401, "forget_seat", "no Authorization header", NO_BEARER),
        _row(method, path, 401, "forget_seat", "the key holds no seat in this circle", NOT_A_MEMBER),
    ]


STATUSES = [
    # ---- circles ----------------------------------------------------------------------------
    _row("POST", "/circles", 201, "success", "the circle, the creator's key and the first join link"),
    _row("POST", "/circles", 422, "show_detail", "the name is over 80 characters", NAME_TOO_LONG),
    _row("POST", "/circles", 422, "show_detail", "the nickname is over 40 characters", NICK_TOO_LONG),
    _row("POST", "/circles", 429, "show_detail", "the day's global ceiling is reached",
         "今天開的圈子太多了，明天再來。"),
    _row("POST", "/circles", 429, "show_detail", "this address has made its circles for the day",
         "你今天開的圈子夠多了，明天再來。"),
    _row("POST", "/circles", 500, "retry_later", "a brand-new circle refused its first seat: a bug"),

    _row("POST", "/circles/{circle_id}/join", 201, "success", "a seat, its key"),
    _row("POST", "/circles/{circle_id}/join", 404, "show_detail", "the ticket is unknown",
         "這個連結沒有用，跟朋友要一次。"),
    _row("POST", "/circles/{circle_id}/join", 409, "show_detail",
         "the circle is full (the sentence names the cap)"),
    _row("POST", "/circles/{circle_id}/join", 410, "show_detail", "the ticket is past its hour",
         "這個連結只能用一小時，過期了。跟開圈子的人要新的。"),
    _row("POST", "/circles/{circle_id}/join", 410, "show_detail", "the ticket was replaced",
         "這個連結換過了，跟開圈子的人要新的。"),
    _row("POST", "/circles/{circle_id}/join", 422, "show_detail", "the name is over 80 characters",
         NAME_TOO_LONG),
    _row("POST", "/circles/{circle_id}/join", 422, "show_detail", "the nickname is over 40 characters",
         NICK_TOO_LONG),

    _row("POST", "/circles/{circle_id}/join/preview", 200, "success", "the circle's name and creator"),
    _row("POST", "/circles/{circle_id}/join/preview", 404, "show_detail",
         "the ticket cannot be used, for any reason (not said which)",
         "這條連結不能用了：可能已經過期（連結只有一小時）、被換掉，或沒有複製完整。開圈子的人可以給一條新的。"),

    _row("POST", "/circles/{circle_id}/join-ticket", 201, "success", "a new join link; the old one dies"),
    *_seat("POST", "/circles/{circle_id}/join-ticket"),
    _row("POST", "/circles/{circle_id}/join-ticket", 403, "show_detail", "only the host may replace it",
         "只有房主可以換連結。"),
    _row("POST", "/circles/{circle_id}/join-ticket", 409, "reread", "replaced a moment ago by another tap",
         "剛剛換過了，重新整理看看。"),

    _row("GET", "/circles/{circle_id}/join-ticket", 200, "success", "the live link"),
    *_seat("GET", "/circles/{circle_id}/join-ticket"),
    _row("GET", "/circles/{circle_id}/join-ticket", 403, "show_detail", "only the host may see it",
         "只有房主可以看連結。"),

    _row("POST", "/circles/{circle_id}/join-ticket/check", 200, "success", "whether a held link is live"),
    *_seat("POST", "/circles/{circle_id}/join-ticket/check"),
    _row("POST", "/circles/{circle_id}/join-ticket/check", 403, "show_detail", "only the host may ask",
         "只有房主可以看連結。"),

    _row("POST", "/circles/{circle_id}/leave", 204, "success",
         "left, or already gone: the same answer in every case, so it is not a probe"),

    _row("DELETE", "/circles/{circle_id}/members/{member_id}", 204, "success", "the seat is removed"),
    *_seat("DELETE", "/circles/{circle_id}/members/{member_id}"),
    _row("DELETE", "/circles/{circle_id}/members/{member_id}", 403, "show_detail",
         "only the host may remove a seat", "只有房主可以請人離開。"),
    _row("DELETE", "/circles/{circle_id}/members/{member_id}", 404, "reread",
         "that seat has already gone", "這個人已經不在圈子裡了。"),
    _row("DELETE", "/circles/{circle_id}/members/{member_id}", 409, "show_detail",
         "the host cannot remove their own seat", "房主不能請自己離開。要離開，請用離開圈子。"),
    _row("DELETE", "/circles/{circle_id}/members/{member_id}", 409, "reread",
         "that seat has submitted in the open round", "這個人已經提交了，不能請對方離開。"),

    _row("GET", "/circles/{circle_id}/members", 200, "success", "the seats"),
    *_seat("GET", "/circles/{circle_id}/members"),

    # ---- the live stream and the place list ---------------------------------------------------
    _row("GET", "/circles/{circle_id}/stream", 200, "success", "the event stream opens"),
    *_seat("GET", "/circles/{circle_id}/stream"),
    _row("GET", "/circles/{circle_id}/places", 200, "success", "places matching the search"),
    *_seat("GET", "/circles/{circle_id}/places"),
    _row("POST", "/circles/{circle_id}/places", 201, "success", "a place added"),
    _row("POST", "/circles/{circle_id}/places", 200, "success", "the place already existed; here it is"),
    *_seat("POST", "/circles/{circle_id}/places"),
    _row("POST", "/circles/{circle_id}/places", 404, "show_detail", "no reference place with that number",
         "no reference place with that 登錄字號"),
    _row("POST", "/circles/{circle_id}/places", 422, "show_detail", "send a name or a number, not both",
         "exactly one of name or registry_no (D28's two doors)"),
    _row("POST", "/circles/{circle_id}/places", 422, "show_detail", "a place needs a name",
         "a place needs a name"),

    # ---- preferences --------------------------------------------------------------------------
    _row("POST", "/circles/{circle_id}/preferences", 204, "success", "stored"),
    *_seat("POST", "/circles/{circle_id}/preferences"),
    _row("POST", "/circles/{circle_id}/preferences", 400, "show_detail",
         "a kind, stance or category the server does not accept: a client bug"),
    _row("POST", "/circles/{circle_id}/preferences", 409, "show_detail",
         "this seat has submitted; take it back first", ALREADY_SUBMITTED),
    _row("POST", "/circles/{circle_id}/preferences", 422, "show_detail", "a retired kind: a client bug"),
    _row("GET", "/circles/{circle_id}/preferences", 200, "success", "this seat's preferences"),
    *_seat("GET", "/circles/{circle_id}/preferences"),

    # ---- rounds -------------------------------------------------------------------------------
    _row("POST", "/circles/{circle_id}/rounds", 201, "success", "the round is open"),
    *_seat("POST", "/circles/{circle_id}/rounds"),
    _row("POST", "/circles/{circle_id}/rounds", 409, "reread",
         "another round is already open; the body carries the one that won"),
    _row("POST", "/circles/{circle_id}/rounds", 422, "show_detail", "the hour has no UTC offset",
         "target_hour must carry a UTC offset (H17)"),

    _row("POST", "/rounds/{round_id}/proposals", 201, "success", "the place is in the pool"),
    _row("POST", "/rounds/{round_id}/proposals", 200, "success", "the place was already in the pool"),
    *_seat("POST", "/rounds/{round_id}/proposals"),
    _row("POST", "/rounds/{round_id}/proposals", 404, "show_detail", "no such round", NO_ROUND),
    _row("POST", "/rounds/{round_id}/proposals", 404, "show_detail", "no such place", "找不到這家店。"),
    _row("POST", "/rounds/{round_id}/proposals", 409, "show_detail", "this seat already proposed three",
         "一個人最多提三家。"),
    _row("POST", "/rounds/{round_id}/proposals", 409, "show_detail",
         "this seat has submitted; take it back first", ALREADY_SUBMITTED),
    _row("POST", "/rounds/{round_id}/proposals", 409, "reread", "the round has closed",
         "這一輪已經擲過了。"),
    _row("POST", "/rounds/{round_id}/proposals", 410, "void", "the round is void", VOID),

    _row("GET", "/rounds/{round_id}/result", 200, "success", "the closed round's result"),
    *_seat("GET", "/rounds/{round_id}/result"),
    _row("GET", "/rounds/{round_id}/result", 404, "show_detail", "no such round", NO_ROUND),
    _row("GET", "/rounds/{round_id}/result", 409, "reread", "the round is still open",
         "這一輪還沒擲出結果。"),
    _row("GET", "/rounds/{round_id}/result", 410, "void", "the round is void", VOID),

    _row("POST", "/rounds/{round_id}/submit", 200, "success",
         "submitted; or the round had already closed and this is its result (D69)"),
    *_seat("POST", "/rounds/{round_id}/submit"),
    _row("POST", "/rounds/{round_id}/submit", 404, "show_detail", "no such round", NO_ROUND),
    _row("POST", "/rounds/{round_id}/submit", 409, "show_detail", "the pool has one place",
         "一輪至少要兩家店。一家店不是決定，是通知。"),
    _row("POST", "/rounds/{round_id}/submit", 409, "show_detail", "this seat joined after the round opened",
         "你是這一輪開始後才加入的，下一輪再一起選。"),
    _row("POST", "/rounds/{round_id}/submit", 409, "show_detail", "nothing in the pool can win",
         "池子是空的，或每一家的機會都是零，擲不出結果。"),
    _row("POST", "/rounds/{round_id}/submit", 410, "void", "the round is void", VOID),

    _row("DELETE", "/rounds/{round_id}/submit", 200, "success", "the submission is taken back"),
    *_seat("DELETE", "/rounds/{round_id}/submit"),
    _row("DELETE", "/rounds/{round_id}/submit", 404, "show_detail", "no such round", NO_ROUND),
    _row("DELETE", "/rounds/{round_id}/submit", 409, "reread", "everyone submitted; the round closed",
         "大家都提交了，已經開獎，收不回來了。"),
    _row("DELETE", "/rounds/{round_id}/submit", 410, "void", "the round is void", VOID),

    _row("POST", "/rounds/{round_id}/trip", 201, "success", "this seat signed the trip"),
    _row("POST", "/rounds/{round_id}/trip", 200, "success", "this seat had already signed it"),
    *_seat("POST", "/rounds/{round_id}/trip"),
    _row("POST", "/rounds/{round_id}/trip", 403, "show_detail", "the round is another circle's",
         "這一輪不屬於你的圈子。"),
    _row("POST", "/rounds/{round_id}/trip", 404, "show_detail", "no such round", NO_ROUND),
    _row("POST", "/rounds/{round_id}/trip", 409, "reread",
         "someone else signed first; the sentence names who and when"),
    _row("POST", "/rounds/{round_id}/trip", 409, "reread", "the round is still open",
         "這一輪還沒擲出結果。"),
    _row("POST", "/rounds/{round_id}/trip", 410, "void", "the round is void", VOID),

    # ---- operator and health endpoints (no screen reads them today) ----------------------------
    _row("GET", "/health", 200, "success", "serving"),
    _row("GET", "/health", 503, "retry_later", "this instance cannot reach the database or the stream"),
    _row("GET", "/places/count", 200, "success", "the registry's place count"),
    _row("GET", "/places/count", 503, "retry_later", "no registry publication yet",
         "no food-business registry publication yet"),
    _row("GET", "/weather", 200, "success", "the reading"),
    _row("GET", "/weather", 404, "show_detail", "no such township or element"),
    _row("GET", "/weather", 422, "show_detail", "the hour has no UTC offset",
         "hour must carry a UTC offset"),
    _row("GET", "/weather", 500, "retry_later", "the stored reading is malformed"),

    # ---- any route ----------------------------------------------------------------------------
    _row("*", "*", 422, "show_detail",
         "the request body failed validation (FastAPI's own; detail is a list, not a sentence)"),
    _row("*", "*", 429, "retry_later", "the proxy's per-address rate (no API sentence)"),
    _row("*", "*", 500, "retry_later", "an unexpected server error"),
    _row("*", "*", 502, "retry_later", "the proxy could not reach the API"),
    _row("*", "*", 503, "retry_later", "unavailable"),
    _row("*", "*", 504, "retry_later", "the proxy timed out"),
    _row("*", "*", 0, "retry_later", "no response at all: the network"),
]
