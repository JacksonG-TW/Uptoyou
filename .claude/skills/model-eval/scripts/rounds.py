#!/usr/bin/env python3
"""rounds.py: one evaluation round per candidate model, against one frozen labelled set.

    rounds.py run   --set testset.json --labels labels.txt --prompt prompt.txt --model <MODEL> [--out rounds/]
                    [--crib crib.json --embed-model <EMBED_MODEL> --k 5]
    rounds.py score rounds/round_<...>.json --set testset.json
    rounds.py table rounds/*.json --set testset.json

Standard library only. The model server is an Ollama-compatible HTTP API named by the OLLAMA_URL
environment variable (http or https); there is no default, so a round never measures a server you did
not name. Every test row, and the crib if one is given, is sent to that server. urllib also honours
the http_proxy and https_proxy variables, so unset them if the data must not pass through a proxy.

- testset.json: a list of {"id", "input", "gold"}, ids unique. Drawn once, labelled once, never re-drawn.
- labels.txt: the allowed answers, one per line. Anything else is a refusal, and a refusal is wrong.
- prompt.txt: the prompt template. {input}, {labels} and {examples} are replaced in it.
- crib.json (optional): labelled examples {"input", "gold"} for retrieval. A crib row whose input is
  the exact same text as the asked row is left out of that row's examples (leave-one-out), so
  retrieval cannot hand the model its answer. Store names byte-identically in both files for that.

The round file's name carries a digest of everything a round is pinned to (model, prompt, labels, test
set, crib, embedder, k), so changing any of them starts a new round in a new file, and the old round
is kept.

Exit codes: 0 done · 1 refused (a file is malformed, the server answered with an error, a stored round
was pinned differently, a round scored before it is complete or against a different test set) · 3 the
model server did not answer; the progress so far is saved and the next run continues at the first
unanswered row.
"""

import argparse
import hashlib
import json
import math
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

SAVE_EVERY = 10
EMBED_BATCH = 64


class ServerError(Exception):
    """The server answered, with an error. Re-running will not help."""


def sha256_of(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def base_url():
    base = os.environ.get("OLLAMA_URL", "")
    if urllib.parse.urlsplit(base).scheme not in ("http", "https"):
        sys.exit("rounds: set OLLAMA_URL to the model server's http(s) base URL (no default, on purpose)")
    return base.rstrip("/")


def post(path, body, timeout=300):
    req = urllib.request.Request(base_url() + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as answered:  # a subclass of URLError: catch it first
        detail = answered.read().decode("utf-8", "replace")[:300]
        try:
            detail = json.loads(detail).get("error", detail)
        except (ValueError, AttributeError):
            pass
        raise ServerError("HTTP {} from {}: {}".format(answered.code, path, detail))


def embed(model, texts):
    vectors = []
    for start in range(0, len(texts), EMBED_BATCH):
        vectors += post("/api/embed", {"model": model, "input": texts[start:start + EMBED_BATCH]})["embeddings"]
    return vectors


def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)) or 1.0)


def parse_answer(text, labels):
    """The first non-empty line, trimmed of quotes and punctuation, must equal one label exactly."""
    line = next((ln for ln in text.splitlines() if ln.strip()), "")
    answer = re.sub(r"^[\s\"'`*.:-]+|[\s\"'`*.:。]+$", "", line)
    return (answer, "answered") if answer in labels else (answer, "refused")


def round_path(out, pinned):
    digest = hashlib.sha256(json.dumps(pinned, sort_keys=True).encode()).hexdigest()[:10]
    return os.path.join(out, "round_{}_{}.json".format(re.sub(r"[^A-Za-z0-9._-]+", "-", pinned["model"]), digest))


def crib_vectors(path, crib, model, crib_sha):
    """The crib's embeddings, cached beside the round so a resume does not embed it again."""
    cache = path + ".crib-vectors.json"
    try:
        stored = load_json(cache)
        if stored.get("crib_sha256") == crib_sha and stored.get("embed_model") == model:
            return stored["vectors"]
    except (OSError, ValueError, AttributeError):
        pass  # absent or unreadable: embed again
    vectors = embed(model, [c["input"] for c in crib])
    with open(cache + ".tmp", "w", encoding="utf-8") as f:
        json.dump({"crib_sha256": crib_sha, "embed_model": model, "vectors": vectors}, f)
    os.replace(cache + ".tmp", cache)
    return vectors


def cmd_run(a):
    testset, labels = load_json(a.set), [ln.strip() for ln in open(a.labels, encoding="utf-8") if ln.strip()]
    ids = [row["id"] for row in testset]
    if len(ids) != len(set(ids)):
        print("rounds: REFUSED, {} has duplicate ids; every row needs its own".format(a.set), file=sys.stderr)
        return 1
    template = open(a.prompt, encoding="utf-8").read()
    rag = None
    if a.crib:
        if not a.embed_model:
            sys.exit("rounds: --crib needs --embed-model")
        rag = {"crib_sha256": sha256_of(a.crib), "embed_model": a.embed_model, "k": a.k}
    pinned = {"model": a.model, "testset_sha256": sha256_of(a.set), "prompt_sha256": sha256_of(a.prompt),
              "labels_sha256": sha256_of(a.labels), "rag": rag}
    os.makedirs(a.out, exist_ok=True)
    path = round_path(a.out, pinned)
    doc = {**pinned, "rows": []}
    if os.path.exists(path):
        doc = load_json(path)
        for key, value in pinned.items():
            if doc.get(key) != value:  # reachable only through a hand-renamed file
                print("rounds: REFUSED, {} has {} = {!r}, this run has {!r}. One round is one measurement."
                      .format(path, key, doc.get(key), value), file=sys.stderr)
                return 1
    done = {row["id"] for row in doc["rows"]}

    def save():
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
        os.replace(path + ".tmp", path)

    asked = 0
    try:
        crib = load_json(a.crib) if rag else []
        vectors = crib_vectors(path, crib, a.embed_model, rag["crib_sha256"]) if rag else []
        for row in testset:
            if row["id"] in done:
                continue
            examples = ""
            if rag:
                q = embed(a.embed_model, [row["input"]])[0]
                ranked = sorted(((cosine(q, v), c) for v, c in zip(vectors, crib)
                                 if c["input"] != row["input"]), key=lambda p: -p[0])
                examples = "\n".join("{} -> {}".format(c["input"], c["gold"]) for _, c in ranked[:a.k])
            prompt = template.replace("{labels}", ", ".join(labels)).replace(
                "{examples}", examples).replace("{input}", row["input"])
            reply = post("/api/generate", {"model": a.model, "prompt": prompt, "stream": False,
                                           "options": {"temperature": 0}})["response"]
            answer, outcome = parse_answer(reply, labels)
            doc["rows"].append({"id": row["id"], "input": row["input"], "gold": row["gold"],
                                "answer": answer, "outcome": outcome, "raw": reply[:200]})
            asked += 1
            if asked % SAVE_EVERY == 0:
                save()
    except ServerError as answered:
        print("rounds: the model server refused: {}. {} rows saved; fix the cause, then re-run".format(
            answered, len(doc["rows"])), file=sys.stderr)
        return 1
    except (urllib.error.URLError, TimeoutError, ConnectionError) as gone:
        print("rounds: the model server did not answer ({}); {} rows saved, re-run to continue".format(
            gone, len(doc["rows"])), file=sys.stderr)
        return 3
    finally:
        if doc["rows"]:
            save()  # whatever ended the loop, the rows already answered are kept
    print("rounds: {} complete, {} rows ({} asked this run)".format(path, len(doc["rows"]), asked))
    return 0


def tally(path, testset_path):
    """(doc, correct, refused, total) recomputed from the rows, never read from a stored number."""
    doc, gold = load_json(path), {r["id"]: r["gold"] for r in load_json(testset_path)}
    if doc["testset_sha256"] != sha256_of(testset_path):
        sys.exit("rounds: REFUSED, {} ran against a test set with sha256 {}…, and {} is now {}…. "
                 "A relabel keeps every row in place, so nothing else would notice.".format(
                     path, doc["testset_sha256"][:12], testset_path, sha256_of(testset_path)[:12]))
    rows = {r["id"]: r for r in doc["rows"]}
    if set(rows) != set(gold):
        return doc, None, None, len(gold)
    correct = sum(r["outcome"] == "answered" and r["answer"] == gold[i] for i, r in rows.items())
    refused = sum(r["outcome"] == "refused" for r in rows.values())
    return doc, correct, refused, len(gold)


def band(correct, total):
    """Half-width, in points, of the 95% sampling interval of a share measured on `total` rows."""
    p = correct / total
    return 196.0 * math.sqrt(p * (1 - p) / total)


def cmd_score(a):
    doc, correct, refused, total = tally(a.round, a.set)
    if correct is None:
        print("{}: incomplete ({} of {} rows); no score until every row is answered".format(
            a.round, len(doc["rows"]), total))
        return 1
    print("{}: {}/{} = {:.1f}% (±{:.1f} points at 95%) · {} refused (counted wrong)".format(
        a.round, correct, total, 100.0 * correct / total, band(correct, total), refused))
    per = {}
    for r in doc["rows"]:
        hit, n = per.get(r["gold"], (0, 0))
        per[r["gold"]] = (hit + (r["outcome"] == "answered" and r["answer"] == r["gold"]), n + 1)
    for label, (hit, n) in sorted(per.items(), key=lambda p: -p[1][1]):
        print("  {:<24} {:>3}/{:<3} {}".format(label, hit, n, "{:.1f}%".format(100.0 * hit / n)
                                               if n >= a.min_rows else "insufficient rows"))
    return 0


def cmd_table(a):
    lines = ["| model | prompt | retrieval | set | correct | score | ±95% | refused |", "|---|---|---|---|---|---|---|---|"]
    for path in a.rounds:  # every round is checked against the set before anything is printed
        doc, correct, refused, total = tally(path, a.set)
        rag = doc.get("rag")
        retrieval = "{} k={}".format(rag["embed_model"], rag["k"]) if rag else "none"
        if correct is None:
            cells = ("{}/{} rows".format(len(doc["rows"]), total), "incomplete", "-", "-")
        else:
            cells = ("{}/{}".format(correct, total), "{:.1f}%".format(100.0 * correct / total),
                     "{:.1f}".format(band(correct, total)), str(refused))
        lines.append("| `{}` | {} | {} | {} | {} | {} | {} | {} |".format(
            doc["model"], doc["prompt_sha256"][:8], retrieval, doc["testset_sha256"][:8], *cells))
    print("\n".join(lines))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--set", required=True)
    r.add_argument("--labels", required=True)
    r.add_argument("--prompt", required=True)
    r.add_argument("--model", required=True)
    r.add_argument("--out", default="rounds")
    r.add_argument("--crib")
    r.add_argument("--embed-model")
    r.add_argument("--k", type=int, default=5, choices=range(1, 21), metavar="1..20")
    s = sub.add_parser("score")
    s.add_argument("round")
    s.add_argument("--set", required=True)
    s.add_argument("--min-rows", type=int, default=5, help="fewer gold rows than this: no percentage")
    t = sub.add_parser("table")
    t.add_argument("rounds", nargs="+")
    t.add_argument("--set", required=True)
    a = ap.parse_args()
    return {"run": cmd_run, "score": cmd_score, "table": cmd_table}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
