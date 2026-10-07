"""A10 — a failed task says so on a phone, once, in one sentence.

*Owner-ruled 2026-08-19.*

**The question.** Every DAG in this repository is nocturnal: 19:00–20:20 UTC is 03:00–04:20 in
Taipei, and the preference erasure runs at 05:00. A red task at 03:20 is discovered when somebody
opens `localhost:8081`, which on a good week is the following evening. `ingest_run`'s daily
heartbeat makes a silently broken source *findable*; it does not make it *noticed*.

So one `on_failure_callback`, shared by every DAG, sending one Telegram message. Not a dashboard,
not a digest, not a second channel for successes — the successes are already in the ledger and a
channel that speaks every night is a channel nobody reads.

**A missing Connection warns and never fails, and this is the load-bearing rule.** The alert is
*about* a failure; an alert that can itself fail turns one red task into two, and the second one
tells you nothing about the pipeline. So every path here is wrapped: no Connection, no network, a
4xx from Telegram, a malformed chat id — each prints a line to the task log and returns. A fresh
clone with no token, and `tools/split_boot_check.sh`'s isolated stack, both run with alerting simply
absent, which is the correct behaviour for a stack nobody is watching.

**What the message may contain, and why this is not a formality.** The text leaves this machine.
`_database_url()` in the ingest DAGs builds `postgresql+asyncpg://user:PASSWORD@db:5432/…`, and a
connection failure's traceback contains it — so a callback that forwarded the exception text
verbatim would post `POSTGRES_PASSWORD` into a chat, from the one code path that only ever runs when
something has already gone wrong and nobody is watching. Three redactions run, in this order, and
the belt-and-braces is deliberate:

1. Airflow's own `redact`, which knows the values of every Connection field this process has read.
2. A regex over `scheme://anything:anything@host`, which catches a URL Airflow never saw.
3. The literal values of the named bootstrap environment variables — including the bot token
   itself, which must never appear in a message it is the transport for.

**Rejected: sending only the identity and «read the log».** It leaks nothing at all and it is what a
first draft of this file did. The cost is that the single most useful sentence — *the row count
collapsed: 12 rows against 14513* — is the sentence a person needs to decide whether to get out of
bed, and withholding it makes the alert a doorbell. Redaction plus a cap keeps the sentence and
closes the leak.

**Rejected: the `apache-airflow-providers-telegram` provider.** One `urllib` POST against a
documented endpoint, against a dependency in the image, a hook to learn, and a second place for the
Connection shape to be defined. Every other outbound call in this repository is stdlib for the same
reason.

**No log URL.** The UI is `localhost:8081`, which is not reachable from the phone the message
arrives on, so a link would be a dead end dressed as an answer. The message carries the log's path
inside the container instead, which is what somebody at a keyboard actually needs.

The Connection is `telegram_alerts`, written delete-then-add by `airflow/init.sh`:
`--conn-type http --conn-host api.telegram.org --conn-login <chat_id> --conn-password <bot token>`.
Rotating the token is `init.sh`'s job — `docker compose up airflow-init --force-recreate --no-deps`
— the same three-places rule the CWA key carries in `CLAUDE.md`.

Tested by `app/api/tests/test_alerts.py` — `compose_message()` and `scrub()` are pure and need no
Airflow, no network and no database.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

CONNECTION_ID = "telegram_alerts"
ENDPOINT = "https://api.telegram.org/bot{}/sendMessage"

# The message is one sentence plus identity. Telegram's own limit is 4096 characters; this cap is
# about the *reader*, who is holding a phone at 03:20, and about how much of a traceback can be
# forwarded before the redaction has more surface than it can be trusted over.
MESSAGE_CAP = 700
DETAIL_CAP = 320
TIMEOUT_SECONDS = 10

# Bootstrap secrets whose literal values are scrubbed out of any detail text. These are exactly the
# names `.env.example` lists, and the airflow services carry them in their environment — so a
# traceback that interpolated one is a traceback that would post it. `TELEGRAM_` is not among them
# because the token arrives from the Connection, not the environment; it is scrubbed separately and
# unconditionally.
SECRET_ENVIRONMENT_NAMES = (
    "POSTGRES_PASSWORD",
    "AIRFLOW_DB_PASSWORD",
    "AIRFLOW_FERNET_KEY",
    "AIRFLOW_JWT_SECRET",
    "AIRFLOW_ADMIN_PASSWORD",
    "UPTO_CWA_API_KEY",
)

# `scheme://user:password@host` — the shape `_database_url()` builds and the shape a driver puts in
# its exception. Non-greedy, and the password class excludes `/` and whitespace so a URL later in
# the same line cannot be swallowed.
CREDENTIAL_URL = re.compile(r"(?P<scheme>[a-zA-Z0-9+.\-]+://)[^/\s:@]+:[^/\s@]+@")

REDACTED = "***"


def scrub(text: str, extra: tuple[str, ...] = ()) -> str:
    """Remove credentials from text that is about to leave this machine.

    Pure, and deliberately not dependent on Airflow: the masker is asked for first inside
    `send_failure_alert`, and this function is the floor under it — the part that still works when
    the masker has never seen the value, which is the case for anything assembled at run time.
    """
    if not text:
        return ""
    cleaned = CREDENTIAL_URL.sub(lambda m: m.group("scheme") + REDACTED + ":" + REDACTED + "@", text)
    values = [os.environ.get(name) for name in SECRET_ENVIRONMENT_NAMES]
    values.extend(extra)
    # Longest first: a short secret that is a substring of a longer one must not carve the longer
    # one into pieces that then fail to match.
    for value in sorted((v for v in values if v and len(v) >= 4), key=len, reverse=True):
        cleaned = cleaned.replace(value, REDACTED)
    return cleaned


# ---- the words a person reads (owner 「告警新格式直接發出來我看」, 2026-10-08) -------------------
#
# **What broke, which data, since when, what it affects, what to do — in that order and in plain
# Chinese**, because the first line is what a phone's notification shows and the reader is not at a
# keyboard. The technical identity (DAG / task / attempt) moves to one small line at the bottom: a
# person at a keyboard finds the log by it, a person on a phone can skip it. The system's own reason
# stays, redacted and clipped, under 「原因」 — it is the line that says *why* (the 2026-08 ruling above
# kept it, and the readable format keeps it).
#
# **Every DAG and every source has a name here, and `test_alerts` fails when one does not** — a new
# job must not ship with an id as its headline.

#: dag_id → (what a person calls it, its kind). The kind picks the headline, the impact and the
#: action; the name is what the reader recognises.
DAG_NAMES: dict[str, tuple[str, str]] = {
    "upto_weather_ingest": ("中央氣象署的天氣資料", "ingest_hourly"),
    "upto_place_reference_ingest": ("食藥署的餐飲業者名冊", "ingest_daily"),
    "upto_brand_ingest": ("臺北市食材登錄的品牌資料", "ingest_daily"),
    "upto_storefront_ingest": ("臺北市衛生評核的店家資料", "ingest_daily"),
    "upto_business_status_ingest": ("經濟部商業登記的營業狀態", "ingest_daily"),
    "upto_business_tax_ingest": ("財政部營業稅籍資料", "ingest_daily"),
    "upto_source_freshness": ("資料新鮮度檢查", "freshness"),
    "upto_db_backup": ("每晚的資料庫備份", "backup"),
    "upto_preference_erasure": ("每晚清除過期偏好", "maintenance"),
    "upto_weather_retention": ("清除舊的天氣資料", "maintenance"),
    "upto_circle_sweep": ("清理閒置的圈子", "maintenance"),
    "upto_dataset_export": ("資料集匯出", "maintenance"),
    "upto_place_classify_backfill": ("店家自動分類", "maintenance"),
    "upto_alert_selftest": ("警報測試", "selftest"),
}

#: task_id → a kind that overrides the DAG's, for the tasks inside an ingest DAG that are checks
#: rather than fetches. Matched by prefix, so `value_check_forecast` is a value check.
TASK_KINDS: tuple[tuple[str, str], ...] = (
    ("value_check", "value"),
    ("check_publication", "publication"),
)

#: The weather DAG's two fetches have names of their own.
TASK_NAMES: dict[str, str] = {
    "observation": "中央氣象署的天氣觀測",
    "forecast": "中央氣象署的天氣預報",
}

#: source id (the ledger's key, `upto.checks.RUN_CADENCE_H`) → what a person calls it.
SOURCE_NAMES: dict[str, str] = {
    "F-D0047-061": "天氣預報（中央氣象署）",
    "O-A0001-001": "天氣觀測（中央氣象署）",
    "fda-97": "餐飲業者名冊（食藥署）",
    "taipei-foodtracer": "品牌資料（臺北市食材登錄）",
    "taipei-hygiene-grade": "衛生評核（臺北市）",
    "gcis-restaurant-registry": "營業狀態（經濟部商業登記）",
    "fia-business-tax": "營業稅籍（財政部）",
}

#: kind → (headline, impact, what to do). `{name}` is the DAG's or task's name.
KIND_TEXT: dict[str, tuple[str, str, str]] = {
    "ingest_hourly": ("❌ {name}這次沒抓到",
                      "網站上的天氣會停在上一次的資料。每小時會自動再試一次。",
                      "只收到一則可以不管；連續收到再處理。"),
    "ingest_daily": ("❌ {name}今天沒抓到",
                     "網站照常運作，店家資料停在上一版。明天同一時間會自動再試。",
                     "不急。明天又收到的話，請 Claude 查。"),
    "freshness": ("⚠️ 有資料停止更新了",
                  "網站照常運作，只是這些資料變舊了。",
                  "不急。請 Claude 查這些排程為什麼沒跑。"),
    "value": ("⚠️ {name}的數字看起來不對",
              "新的一版已經存進資料庫。如果數字真的錯了，網站可能會用到錯的資料。",
              "請 Claude 看這一版資料是不是真的有問題。"),
    "publication": ("⚠️ {name}的新一版跟上一版長得不一樣",
                    "新的一版已經存進資料庫，但欄位變了或筆數掉太多，店名可能開始對不起來。",
                    "請 Claude 比對這一版和上一版。"),
    "backup": ("❌ {name}失敗了",
               "今天沒有新的備份；之前的備份還在。",
               "今天內請 Claude 查。連續兩天沒備份就比較危險。"),
    "maintenance": ("❌ {name}沒有完成",
                    "網站照常運作。下一次排程會自動再試。",
                    "不急。連續收到再請 Claude 查。"),
    "unknown": ("❌ {name}失敗了",
                "不確定影響範圍。",
                "請 Claude 查。"),
}

#: The self-test is the one message that reports success; it must never read like an outage.
SELFTEST_TEXT = "✅ 警報測試成功\n這是一則測試訊息，代表警報管道是通的，不用處理。"

TAIPEI_OFFSET_HOURS = 8   # Taiwan keeps no daylight saving (since 1979), so the offset is the zone.


def _taipei(moment) -> str:
    """`10月8日 11:00` on Taipei's clock, from an aware datetime; empty when there is none."""
    from datetime import timedelta, timezone

    if moment is None:
        return ""
    local = moment.astimezone(timezone(timedelta(hours=TAIPEI_OFFSET_HOURS)))
    return "{}月{}日 {:%H:%M}".format(local.month, local.day, local)


def _duration(hours: float) -> str:
    """`6 天 20 小時`, `3 小時`, `40 分鐘` — the unit a person would say."""
    if hours < 1:
        return "{} 分鐘".format(max(1, int(round(hours * 60))))
    days, rest = divmod(int(round(hours)), 24)
    if days and rest:
        return "{} 天 {} 小時".format(days, rest)
    if days:
        return "{} 天".format(days)
    return "{} 小時".format(rest)


def _cadence(hours: float) -> str:
    return "每小時一次" if hours <= 1 else "每天一次" if hours <= 24 else "每 {} 一次".format(_duration(hours))


def _finding_line(finding: dict, now) -> str:
    """One bullet per finding, from the structured fields the check attached — never parsed back
    out of its English sentence."""
    from datetime import timedelta

    source = finding.get("source", "")
    name = SOURCE_NAMES.get(source, source)
    metric = finding.get("metric", "")
    value = finding.get("value")
    cadence = finding.get("cadence_h")
    if metric == "hours_since_last_run" and value is not None:
        line = "• {}：已經 {}沒有更新".format(name, _duration(value))
        if cadence:
            line += "（平常{}）".format(_cadence(cadence))
        if now is not None:
            line += "。上次：{}".format(_taipei(now - timedelta(hours=value)))
        return line
    if metric == "hours_since_last_stored" and value is not None:
        line = "• {}：已經 {}沒有新的一版".format(name, _duration(value))
        interval = finding.get("interval_h")
        if interval:
            line += "（平常約{}有一版）".format(_cadence(interval).replace("一次", ""))
        return line
    if metric == "row_step" and value is not None:
        return "• {}：資料筆數一次變了 {:.0f}%（超過 {:.0f}% 就提醒）".format(
            name, value * 100, (finding.get("threshold") or 0) * 100)
    return "• {}：{}".format(name, finding.get("sentence", metric))


def _plain_reason(detail: str) -> str:
    """The common causes in words; anything else is the system's own text, already redacted."""
    lowered = detail.lower()
    # **The source is blamed only when the detail names a web request** (the reviewer's catch,
    # 2026-10-08): our own Postgres also answers «connection refused» while it restarts in a deploy,
    # and a «statement timeout» is ours too. Without a URL or a URLError the wording names nobody.
    remote = "urlerror" in lowered or "http://" in lowered or "https://" in lowered
    if "timed out" in lowered or "timeout" in lowered:
        return "連線逾時（資料來源的網站沒有回應）" if remote else "連線逾時（不確定是外部網站還是我們自己的服務）"
    if any(token in lowered for token in ("name or service not known", "connection refused",
                                          "urlerror", "temporary failure in name resolution")):
        return "連不上資料來源的網站" if remote else "連不上某個服務（可能是外部網站，也可能是我們自己的資料庫）"
    if "memoryerror" in lowered or "sigkill" in lowered or "out of memory" in lowered:
        return "記憶體不夠，程式被系統停掉"
    clipped = detail if len(detail) <= DETAIL_CAP else detail[: DETAIL_CAP - 1] + "…"
    return "（系統原文）" + clipped if clipped else ""


def kind_of(dag_id: str, task_id: str) -> str:
    for prefix, kind in TASK_KINDS:
        if task_id.startswith(prefix):
            return kind
    return DAG_NAMES.get(dag_id, ("", "unknown"))[1]


def compose_message(
    dag_id: str,
    task_id: str,
    run_id: str,
    try_number: int,
    max_tries: int,
    detail: str,
    log_path: str = "",
    findings: list | None = None,
    started=None,
    now=None,
) -> str:
    """The whole message. Pure — no Airflow, no network.

    Headline, what happened, impact, what to do, then one technical line. `findings` are the
    structured rows a check attached to its exception (`source`, `metric`, `value`, …); `started`
    and `now` are aware datetimes, absent in a context that has none.
    """
    total = max_tries + 1 if max_tries else 0
    attempts = "第 {} 次（共 {} 次）".format(try_number, total) if total else "第 {} 次".format(try_number)
    # **No container path** (the readable format's promise): the DAG, task and attempt are enough for
    # a person at a keyboard to find the log; `log_path` is accepted and deliberately not printed.
    footer = "—\n{} / {} · {}".format(dag_id, task_id, attempts)

    kind = kind_of(dag_id, task_id)
    if kind == "selftest":
        return SELFTEST_TEXT + "\n" + footer

    name = TASK_NAMES.get(task_id) or DAG_NAMES.get(dag_id, (dag_id, "unknown"))[0]
    headline, impact, action = KIND_TEXT.get(kind, KIND_TEXT["unknown"])
    lines = [headline.format(name=name)]
    if findings:
        lines.extend(_finding_line(finding, now) for finding in findings)
    else:
        when = _taipei(started)
        tries = "，重試 {} 次都沒成功".format(total - 1) if total > 1 else ""
        lines.append("{}{}這一次失敗{}。".format(name, "，{} ".format(when) if when else "", tries))
        reason = _plain_reason(detail)
        if reason:
            lines.append("原因：" + reason)
    lines.append("影響：" + impact)
    lines.append("要做什麼：" + action)
    lines.append(footer)
    message = "\n".join(lines)
    return message if len(message) <= MESSAGE_CAP else message[: MESSAGE_CAP - 1] + "…"


def _log_path(dag_id: str, run_id: str, task_id: str, try_number: int) -> str:
    """Where the log actually is inside the airflow containers.

    Not a URL. The UI is on `localhost:8081`, unreachable from the phone this arrives on, so a link
    would be a dead end dressed as an answer. This path is what somebody at a keyboard needs, and it
    is the layout measured on this stack 2026-08-19 while reading A9's own run.
    """
    return "/opt/airflow/logs/dag_id={}/run_id={}/task_id={}/attempt={}.log".format(
        dag_id, run_id, task_id, try_number)


def send_failure_alert(context) -> None:
    """`on_failure_callback` for every DAG in this repository. Never raises, whatever happens.

    Airflow calls this after the retries are spent, so one failed task is one message.
    """
    try:
        _send(context)
    except BaseException as problem:  # noqa: BLE001 — see the docstring: it may not raise
        # Printed, so it lands in the task log of the task that already failed. An alert that
        # fails is worth knowing about and is not worth a second red task.
        print("alert: could not send the failure alert ({}: {}) — the task's own failure above is "
              "the one that matters".format(type(problem).__name__, problem))


def _send(context) -> None:
    from airflow.hooks.base import BaseHook

    instance = context.get("task_instance")
    dag_id = getattr(instance, "dag_id", "") or str(context.get("dag", ""))
    task_id = getattr(instance, "task_id", "") or ""
    run_id = getattr(instance, "run_id", "") or ""
    try_number = getattr(instance, "try_number", 0) or 0
    max_tries = getattr(instance, "max_tries", 0) or 0

    raw = context.get("exception")
    detail = "" if raw is None else "{}: {}".format(type(raw).__name__, raw)
    # A check attaches its findings as data (`_value_check.raise_findings`), so the message is built
    # from fields rather than parsed back out of an English sentence. Numbers and source ids only —
    # nothing in them is secret, and they bypass no redaction because none of them is free text.
    findings = getattr(raw, "findings", None)
    started = getattr(instance, "start_date", None)

    # Airflow's own masker knows every Connection value this process has read — including the bot
    # token below, once the Connection has been fetched. Asked for first and tolerated absent: the
    # import path moved between Airflow 2 and 3 (`airflow.utils.log.secrets_masker` does not exist
    # in 3.0.2, measured), and `scrub` is the floor that does not depend on it.
    try:
        from airflow.sdk.execution_time.secrets_masker import redact

        detail = str(redact(detail))
    except Exception:  # noqa: BLE001 — an absent masker is not a reason to send nothing
        pass

    try:
        connection = BaseHook.get_connection(CONNECTION_ID)
    except Exception as missing:  # noqa: BLE001
        print("alert: no `{}` Connection ({}), so no message was sent — alerting is off on this "
              "stack, which is the designed state for one nobody is watching".format(
                  CONNECTION_ID, type(missing).__name__))
        return

    token = (connection.password or "").strip()
    chat_id = (connection.login or "").strip()
    if not token or not chat_id:
        print("alert: the `{}` Connection is missing its {} — nothing sent".format(
            CONNECTION_ID, "password (bot token)" if not token else "login (chat id)"))
        return

    detail = scrub(detail, extra=(token,))
    from datetime import datetime, timezone

    message = compose_message(
        dag_id, task_id, run_id, try_number, max_tries, detail,
        _log_path(dag_id, run_id, task_id, try_number),
        findings=findings, started=started, now=datetime.now(timezone.utc))

    # **Scrubbed once more as a whole, right before it leaves** (the reviewer's note): the findings
    # bypass the detail's redaction because they are numbers and source ids, and a finding line
    # that falls back to its sentence prints that sentence verbatim — so the guarantee holds by
    # construction here rather than by what today's checks happen to write.
    message = scrub(message, extra=(token,))
    payload = json.dumps({"chat_id": chat_id, "text": message}).encode("utf-8")
    request = urllib.request.Request(
        ENDPOINT.format(token),
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            code = response.status
    except urllib.error.HTTPError as refused:
        # **`HTTPError` before `URLError`, because it is a subclass of it.** Telegram said no — a
        # wrong chat id, a revoked token — and that is a different thing to fix from "no network",
        # so it gets its own line. The body is read and *not* forwarded: it echoes the request.
        print("alert: Telegram refused the message (HTTP {}) — check the `{}` Connection's chat id "
              "and token; the task's own failure above is unaffected".format(
                  refused.code, CONNECTION_ID))
        return
    except urllib.error.URLError as unreachable:
        print("alert: could not reach Telegram ({}) — nothing sent, and the task's own failure "
              "above is unaffected".format(unreachable.reason))
        return
    print("alert: failure alert sent for {} / {} (HTTP {})".format(dag_id, task_id, code))
