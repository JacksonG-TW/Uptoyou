"""D64's metrics: one round file plus the frozen set, in — one report, out. Pure and re-runnable.

    python -m upto.evaluate.score evaluation/round_qwen_v3-2026-08-14.json

Prints the report and writes the same bytes to `<round-file>.report.md`. One renderer feeds
both, so what a reader sees in the terminal is what the commit carries.

**The gold labels are read fresh from the CURRENT test set every time, never from the round
file.** The set is frozen against re-drawing, not against the owner's corrections — D82's
review already moved labels once, and a stored round scored against its own stale copy would
quietly report yesterday's answer. The round file still carries the gold it was asked under,
and the difference between the two is printed as drift rather than swallowed: a row whose
gold changed since the round ran is scored under the new label and counted in a line that
says so.

**The report prints the sha256 of the testset file it scored against.** Two reports are
comparable when that digest matches and visibly not when it does not, which is the whole
claim D82 freezes a file to make.

The metric order is D82's: **per name-layer first, pooled second** — the draw's floor
over-weights the sign layer relative to deployment, so the pooled number alone would flatter
or punish a candidate for the draw's shape rather than its own accuracy.

**A refusal counts as wrong.** An answer outside D38's list is not a near-miss to be repaired
(D39's condition 2); in the pipeline it leaves the row unwritten, so in the evaluation it
leaves the row unscored-as-correct. It gets its own column, `無效`, so a candidate that fails
loudly is distinguishable from one that is confidently wrong — those are different problems
and the confusion matrix is where the difference shows.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import unicodedata

from upto.classify.categories import CATEGORIES
from upto.classify.prompt import NO_SIGNAL

# Every value a gold label may hold **today**: D38's eleven plus D79's recorded verdict.
LABELS: tuple[str, ...] = CATEGORIES + (NO_SIGNAL,)

# The value only a candidate can produce. It is never a gold label — nothing in the frozen set is
# unreadable — so it is a column and not a row.
INVALID = "無效"
PREDICTED: tuple[str, ...] = LABELS + (INVALID,)


def label_space(gold_rows: list[dict], scored: list[dict]) -> tuple[tuple, tuple]:
    """The rows and columns of THIS round's tables, taken from the set it was scored against.

    **Added 2026-08-30 with `testset_v2.json`, and the reason is a report that changed without
    its numbers changing.** The tables used to be built from `CATEGORIES`, so the moment D38 gained
    `便利商店` every old report re-rendered with an extra empty row and column — a v5 round
    displaying a category that did not exist when it ran. The numbers were identical; the shape
    lied. A report should describe the run it reports.

    Rows are the gold labels actually present in the set. Columns are those plus anything the
    candidate answered that is not among them (so a v6 model answering 便利商店 against a v1 set
    is *shown* rather than silently dropped from the matrix), plus `無效` last. Order follows
    `PREDICTED`, so two reports over the same set still line up column for column.
    """
    present = {row.get("label") for row in gold_rows}
    answered = {row.get("predicted") for row in scored}
    rows = tuple(label for label in LABELS if label in present)
    extra = tuple(label for label in PREDICTED
                  if label not in rows and label in answered and label != INVALID)
    return rows, rows + extra + (INVALID,)

LAYERS: tuple[str, ...] = ("sign", "brand", "registered")

#: Below this many gold rows a per-label accuracy is not reported — the report says
#: «insufficient rows» instead. **Five, and the number is a judgement rather than a statistic**:
#: at n = 1 the answer is 0% or 100%, at n = 5 one miss is 20 points, and there is no honest
#: threshold that makes a small sample large. It is set where a reader would stop quoting the
#: figure, and the pooled and per-layer numbers are unaffected — every row still counts there.
MIN_SCOREABLE_ROWS = 5
LAYER_NAMES = {"sign": "sign 招牌", "brand": "brand 品牌", "registered": "registered 登記"}

# **The current set is v3 since 2026-08-30** (D38's twelfth and thirteenth values, 台菜 and
# 素食 — one row relabelled under an owner ruling; same 200 rows, same draw. v2 added 便利商店). `testset_v1.json` stays on disk unchanged so
# every round scored against it remains interpretable, and a v5 round is never re-scored against
# v2 — `report_for` refuses that rather than doing it quietly. Read `_refuse_wrong_testset`.
TESTSET_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "testset_v3.json")


# --- the frozen set -------------------------------------------------------------------


def sha256_of(path: str) -> str:
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def testset_rows(document) -> list[dict]:
    """The set is a document with a `rows` list; a bare list is accepted for a fabricated one."""
    return document["rows"] if isinstance(document, dict) else list(document)


def load_testset(path: str = TESTSET_PATH) -> tuple[list[dict], str]:
    with open(path, encoding="utf-8") as handle:
        document = json.load(handle)
    return testset_rows(document), sha256_of(path)


# --- scoring --------------------------------------------------------------------------


def predicted_of(row: dict) -> str:
    """What the candidate answered, mapped onto the 12 columns.

    `outcome` is the authority and `answer` is the value — a refusal carries no value at all,
    which is why it cannot simply be compared as a string.
    """
    outcome = row.get("outcome")
    if outcome == "refused":
        return INVALID
    if outcome == "no_signal":
        return NO_SIGNAL
    answer = row.get("answer")
    return answer if answer in LABELS else INVALID


def align(round_rows: list[dict], gold_rows: list[dict]) -> tuple[list[dict], list[dict], list[int]]:
    """Join a round's answers to the current gold. Returns (scored, stale, unanswered).

    Rows are joined on `i`, the position in the frozen set, **and the name is checked**: if
    the set was amended under a stored answer, that answer is about a different string and is
    stale rather than wrong. Scoring a stale row either way would be a measurement of the
    edit, not of the candidate.
    """
    answered = {row["i"]: row for row in round_rows if isinstance(row.get("i"), int)}
    scored: list[dict] = []
    stale: list[dict] = []
    unanswered: list[int] = []
    for index, gold_row in enumerate(gold_rows):
        row = answered.get(index)
        if row is None:
            unanswered.append(index)
            continue
        if row.get("name") != gold_row.get("name"):
            stale.append({"i": index, "asked": row.get("name"), "now": gold_row.get("name")})
            continue
        gold = gold_row.get("label")
        predicted = predicted_of(row)
        scored.append(
            {
                "i": index,
                "name": gold_row.get("name"),
                "layer": gold_row.get("layer"),
                "gold": gold,
                "gold_stored": row.get("gold"),
                "predicted": predicted,
                "correct": predicted == gold,
            }
        )
    return scored, stale, unanswered


def tally(scored: list[dict], labels: tuple = LABELS, predicted: tuple = PREDICTED) -> dict:
    """Every table in the report, counted once. Pure: same rows in, same numbers out.

    `labels` / `predicted` come from `label_space` so the tables describe the set that was
    scored; the defaults are today's space, for callers that have no set to hand.
    """
    per_layer = {layer: [0, 0] for layer in LAYERS}  # [correct, total]
    per_label = {label: [0, 0] for label in labels}
    confusion = {gold: {p: 0 for p in predicted} for gold in labels}
    correct = total = 0
    for row in scored:
        total += 1
        correct += 1 if row["correct"] else 0
        if row["layer"] in per_layer:
            per_layer[row["layer"]][1] += 1
            per_layer[row["layer"]][0] += 1 if row["correct"] else 0
        if row["gold"] in per_label:
            per_label[row["gold"]][1] += 1
            per_label[row["gold"]][0] += 1 if row["correct"] else 0
        if row["gold"] in confusion and row["predicted"] in confusion[row["gold"]]:
            confusion[row["gold"]][row["predicted"]] += 1
    return {
        "per_layer": per_layer,
        "per_label": per_label,
        "confusion": confusion,
        "pooled": [correct, total],
        "invalid": sum(1 for row in scored if row["predicted"] == INVALID),
        "drifted": sum(
            1 for row in scored if row["gold_stored"] is not None and row["gold_stored"] != row["gold"]
        ),
    }


# --- rendering ------------------------------------------------------------------------


def width(text: str) -> int:
    """Display width in a monospace terminal: a wide or fullwidth glyph occupies two cells."""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in str(text))


def pad(text: str, cells: int, right: bool = False) -> str:
    filler = " " * max(0, cells - width(text))
    return filler + str(text) if right else str(text) + filler


def table(header: list[str], rows: list[list[str]], numeric_from: int = 1) -> list[str]:
    """A markdown pipe table whose cells are padded by display width.

    Padded this way it reads as a table in a terminal *and* renders as one in the commit —
    one string for both outputs, which is what keeps the printed report and the written file
    from drifting apart.
    """
    columns = len(header)
    widths = [width(header[c]) for c in range(columns)]
    for row in rows:
        for c in range(columns):
            widths[c] = max(widths[c], width(row[c]))
    def line(cells: list[str]) -> str:
        return "| " + " | ".join(
            pad(cells[c], widths[c], right=c >= numeric_from) for c in range(columns)
        ) + " |"
    rule = "|" + "|".join(
        ("-" * (widths[c] + 1) + ":") if c >= numeric_from else (":" + "-" * (widths[c] + 1))
        for c in range(columns)
    ) + "|"
    return [line(header), rule] + [line(row) for row in rows]


def percent(correct: int, total: int) -> str:
    return "—" if total == 0 else f"{100.0 * correct / total:.1f}%"


def render(round_doc: dict, scored: list[dict], stale: list[dict], unanswered: list[int],
           counts: dict, testset_path: str, testset_digest: str,
           labels: tuple = LABELS, predicted: tuple = PREDICTED) -> str:
    """The whole report as one string. No clock is read here — same inputs, same bytes."""
    lines: list[str] = []
    candidate = round_doc.get("candidate", "?")
    lines.append(f"# Evaluation round — {candidate}")
    lines.append("")
    lines.append(f"- **candidate**: `{candidate}`")
    lines.append(f"- **model**: `{round_doc.get('model', '?')}`")
    lines.append(f"- **prompt version**: `{round_doc.get('prompt_version', '?')}`")
    # D88's second axis, printed only for a retrieval round. Without it the nine cells of the
    # 3-embedder × 3-generator matrix render identical headers — the prompt version is the
    # same for all nine by design (the embedder is a retrieval variable, not a prompt one), so
    # the embedding model is the only thing on the page that tells two of them apart.
    retrieval = round_doc.get("rag")
    if retrieval:
        lines.append(f"- **retrieval (D88)**: `{retrieval.get('embed_model', '?')}`, "
                     f"k={retrieval.get('k', '?')}")
    lines.append(f"- **started / finished**: {round_doc.get('started_at', '?')} → "
                 f"{round_doc.get('finished_at') or '(unfinished)'}")
    lines.append(f"- **test set**: `{os.path.basename(testset_path)}`")
    lines.append(f"- **test set sha256**: `{testset_digest}`")
    lines.append(f"- **scored**: {len(scored)} rows"
                 + (f" · **unanswered**: {len(unanswered)}" if unanswered else "")
                 + (f" · **stale (the set was amended under the answer)**: {len(stale)}"
                    if stale else ""))
    if counts["drifted"]:
        lines.append(f"- **gold changed since the round ran**: {counts['drifted']} rows — scored "
                     "under the current label, which is the point of reading gold fresh")
    lines.append("")
    lines.append("Two reports compare only when the sha256 above matches. A refusal or an "
                 "answer outside D38's list counts as wrong and lands in the `無效` column.")
    lines.append("")

    lines.append("## Accuracy by name layer (D82: this one first)")
    lines.append("")
    rows = []
    for layer in LAYERS:
        got, seen = counts["per_layer"][layer]
        rows.append([LAYER_NAMES.get(layer, layer), str(seen), str(got), percent(got, seen)])
    lines += table(["layer", "n", "correct", "accuracy"], rows)
    lines.append("")

    correct, total = counts["pooled"]
    lines.append("## Pooled (second, and never on its own)")
    lines.append("")
    lines += table(["set", "n", "correct", "accuracy"],
                   [["all layers", str(total), str(correct), percent(correct, total)],
                    ["of which 無效", str(total), str(counts["invalid"]),
                     percent(counts["invalid"], total)]])
    lines.append("")

    lines.append("## Accuracy by gold label")
    lines.append("")
    # **A label the set cannot measure prints «insufficient rows», never a percentage.** 素食 is
    # ~1% of the city and the frozen draw holds ONE row of it, so its accuracy is 0% or 100% and
    # means neither — and a reader comparing two rounds would be comparing one coin flip. This is
    # M2's own shape, where a source with a single publication prints *insufficient history*
    # rather than a number derived from one interval. **The threshold is stated, not implied**: it
    # is `n < MIN_SCOREABLE_ROWS`, so the day a targeted set makes 素食 measurable the column
    # appears by itself.
    rows = []
    for label in labels:
        got, seen = counts["per_label"][label]
        rows.append([label, str(seen), str(got),
                     "insufficient rows" if 0 < seen < MIN_SCOREABLE_ROWS
                     else percent(got, seen)])
    lines += table(["gold", "n", "correct", "accuracy"], rows)
    lines.append("")

    lines.append("## Confusion — gold down, answered across")
    lines.append("")
    header = ["gold ＼ answered"] + list(predicted)
    rows = []
    for gold in labels:
        cells = [gold]
        for column in predicted:
            value = counts["confusion"][gold][column]
            cells.append(str(value) if value else "")
        rows.append(cells)
    lines += table(header, rows)
    lines.append("")
    if stale:
        lines.append("## Stale rows — answered, then the set was amended")
        lines.append("")
        lines += table(["i", "asked as", "now reads"],
                       [[str(row["i"]), str(row["asked"]), str(row["now"])] for row in stale],
                       numeric_from=0)
        lines.append("")
    return "\n".join(lines) + "\n"


def _refuse_wrong_testset(round_doc: dict, testset_path: str, digest: str) -> None:
    """Refuse to score a round against a set that is not the one it was run on.

    **Added 2026-08-30 with `testset_v2.json`, and it closes a hole that only existed once there
    was a second set to be wrong about.** `align`'s `stale` list compares the NAME at each index,
    so it catches a re-*draw* — different rows — and reports it in the report. A re-*label* keeps
    every name identical at every index, so `stale` stays empty and an old round would re-score
    against new gold **silently**, printing a report that looks exactly like the committed one
    with different numbers in it. The sha256 was already in the report; it was printed and never
    compared, which is H34's shape — a value shown to a reader in place of a check.

    The round file records both the filename and the sha it ran against, so this is a comparison
    of two facts the round already carries, not a new one to maintain.
    """
    ran_on = round_doc.get("testset")
    ran_sha = round_doc.get("testset_sha256_at_run")
    here = os.path.basename(testset_path)
    if ran_on and ran_on != here:
        raise SystemExit(
            "this round was run against {} and you are scoring it against {}. Score it with its "
            "own set — `--testset .../{}` — or the numbers are a comparison nobody made. D82 "
            "keeps every set on disk exactly so the old one is still there.".format(
                ran_on, here, ran_on))
    if ran_sha and ran_sha != digest:
        raise SystemExit(
            "{} has changed since this round ran: the round recorded sha256 {} and the file is "
            "now {}. A relabel leaves every name in place, so nothing else here would have "
            "noticed. Score against the file the round names, or re-run the round.".format(
                here, ran_sha[:16] + "…", digest[:16] + "…"))


def report_for(round_path: str, testset_path: str = TESTSET_PATH) -> str:
    with open(round_path, encoding="utf-8") as handle:
        round_doc = json.load(handle)
    gold_rows, digest = load_testset(testset_path)
    _refuse_wrong_testset(round_doc, testset_path, digest)
    scored, stale, unanswered = align(round_doc.get("rows", []), gold_rows)
    labels, predicted = label_space(gold_rows, scored)
    counts = tally(scored, labels, predicted)
    return render(round_doc, scored, stale, unanswered, counts, testset_path, digest,
                  labels, predicted)


def main(argv: list[str]) -> int:
    testset_path = TESTSET_PATH
    argv = list(argv)
    if "--testset" in argv:
        at = argv.index("--testset")
        if at + 1 >= len(argv):
            print("--testset needs a path", file=sys.stderr)
            return 2
        testset_path = argv[at + 1]
        del argv[at:at + 2]
    if len(argv) != 1:
        print("usage: python -m upto.evaluate.score [--testset <file>] <round-file>",
              file=sys.stderr)
        return 2
    round_path = argv[0]
    if not os.path.exists(round_path):
        print(f"no round file at {round_path} — run `python -m upto.evaluate.run_round "
              "<candidate>` first", file=sys.stderr)
        return 2
    text = report_for(round_path, testset_path)
    sys.stdout.write(text)
    destination = round_path + ".report.md"
    with open(destination, "w", encoding="utf-8") as handle:
        handle.write(text)
    print(f"\nwritten: {destination}", file=sys.stderr)
    # D63, owner-ruled 2026-08-14: the report is the public half of a round and the raw round
    # file is not. Writing the public copy here keeps "one public commit per round" mechanical
    # rather than a hand-copy that gets forgotten. Four parents up from this file is `app/` in
    # the private checkout and the repository root in the extracted public one — same place.
    app_dir = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                           "..", "..", "..", ".."))
    public = os.path.join(app_dir, "evaluation",
                          os.path.basename(round_path) + ".report.md")
    os.makedirs(os.path.dirname(public), exist_ok=True)
    with open(public, "w", encoding="utf-8") as handle:
        handle.write(text)
    print(f"public copy: {public}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
