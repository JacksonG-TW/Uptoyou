#!/usr/bin/env python3
"""D82's draw, the half that needs no database: allocation and determinism.

    python3 app/api/tests/test_evaluate_draw.py

What matters here is that the draw is a *function* — same populations, same seed, same rows
out — because the frozen set's whole claim to comparability rests on the draw being
reproducible against the same publication.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from upto.evaluate.draw import (  # noqa: E402
    FLOOR, HELDOUT_SEED, LAYERS, SIZE, SEED, allocate, pick, pick_heldout,
)

RAN = 0


def check(condition, message):
    global RAN
    RAN += 1
    assert condition, message


def rows_for(populations):
    rows = []
    for layer, count in populations.items():
        for i in range(count):
            rows.append(
                {"registry_no": f"{layer[:2]}-{i:05d}", "name": f"{layer}{i}", "layer": layer}
            )
    return rows


# Allocation: the measured-shaped case — signs small, registered dominant.
songshan_like = {"sign": 104, "brand": 240, "registered": 2980}
counts = allocate(songshan_like)
check(sum(counts.values()) == SIZE, f"allocation must sum to {SIZE}, got {counts}")
check(all(counts[l] >= min(FLOOR, songshan_like[l]) for l in LAYERS), f"floor violated: {counts}")
check(all(counts[l] <= songshan_like[l] for l in LAYERS), f"over-drew a layer: {counts}")
check(
    counts["registered"] > counts["brand"] > counts["sign"],
    f"proportionality lost above the floor: {counts}",
)

# A layer smaller than the floor contributes everything it has, and the total still lands.
tiny_sign = {"sign": 7, "brand": 300, "registered": 3000}
counts = allocate(tiny_sign)
check(counts["sign"] == 7, f"a 7-row layer must contribute all 7, got {counts}")
check(sum(counts.values()) == SIZE, f"total must still be {SIZE}, got {counts}")

# Populations barely above SIZE: everything that exists is taken, never more.
scarce = {"sign": 10, "brand": 20, "registered": 100}
counts = allocate(scarce)
check(counts == scarce, f"with only 130 rows the draw is all of them, got {counts}")

# The draw: deterministic, allocation-shaped, and sorted output.
pool = rows_for(songshan_like)
first = pick(pool)
second = pick(list(reversed(pool)))  # input order must not matter
check(first == second, "same seed and rows must reproduce the same draw")
check(len(first) == SIZE, f"draw size {len(first)} != {SIZE}")
by_layer = {layer: sum(1 for r in first if r["layer"] == layer) for layer in LAYERS}
check(by_layer == allocate(songshan_like), f"draw {by_layer} disagrees with allocation")
check(
    [r["registry_no"] for r in first] == sorted(r["registry_no"] for r in first),
    "output must be sorted by registry_no so the frozen file diffs stably",
)
check(len({r["registry_no"] for r in first}) == SIZE, "a row was drawn twice")

# A different seed is a different draw — the seed is doing something.
check(pick(pool, seed=83) != first, "seed 83 drew the identical set; the seed is inert")

# The held-out draw (owner 「A」, 2026-10-11): disjoint from the frozen draw by construction,
# allocated on what is left, and its own seed.
frozen = pick(pool)
excluded = {r["registry_no"] for r in frozen}
held = pick_heldout(pool, excluded)
check(len(held) == SIZE, f"held-out size {len(held)} != {SIZE}")
check(not excluded & {r["registry_no"] for r in held}, "a frozen row was drawn into the held-out set")
left = {layer: songshan_like[layer] - sum(1 for r in frozen if r["layer"] == layer) for layer in LAYERS}
check({layer: sum(1 for r in held if r["layer"] == layer) for layer in LAYERS} == allocate(left),
      "the held-out allocation must be computed on the rows left after the exclusion")
check(pick_heldout(list(reversed(pool)), excluded) == held, "the held-out draw must reproduce")
check(HELDOUT_SEED != SEED, "the held-out draw must not reuse the frozen seed")

print(f"ok — {RAN} checks: the draw is a function of (rows, seed) and nothing else")
