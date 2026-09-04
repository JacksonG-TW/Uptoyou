# The brand crib — one round per candidate, against D77's 288 brand names

*Run 2026-09-04. Owner-ruled 「做」 (grow the crib) and 「縮」 (narrow D88's hold-out).
Prompt `v7-rag-2026-08-30` unchanged · `testset_v3` unchanged · arctic bare · k=5 · GPU box.*

> **「A lift here means the chain is in the crib now, not that the model got smarter.」**
> — the owner, ruled in advance of the round.

That sentence is the finding, and the layer table below is what it looks like as numbers.

---

## 0. CORRECTION — the first pair was confounded, and these are the clean numbers

**The round pair first published here was not comparable to its baseline.** The v7 baselines
finished `2026-08-30T15:26Z`, the day **before** revision 0041 introduced embedding prefixes, so
their cribs were embedded **bare**. The first brand-crib rounds ran with `prefix_kind = 'query'`,
because `EMBED_PREFIX["arctic"]` still said `query: ` — **the 2026-08-31 ruling («the embedder axis
closes: arctic, bare, stays») had never reached the code.** Same candidate, prompt, embedder, k and
test set; different retrieval, and **neither round file recorded the field that differed** (H72).

**Everything below is the re-run, bare crib against bare baseline.** The confounded pair is kept
as `_brandcrib` for the record and must not be quoted.

| | crib | prefix | gemma | qwen7b |
|---|---|---|---|---|
| baseline | test set only | bare | 142 · 71.0 | 144 · 72.0 |
| *confounded, do not quote* | + 288 brands | `query: ` | 145 · 72.5 | 152 · 76.0 |
| **clean** | **+ 288 brands** | **bare** | **147 · 73.5** | **151 · 75.5** |

**The prefix cost ~1.0 point on gemma against the kNN screen's independently measured 1.5** — same
sign, same order, two instruments. The crib's effect was *understated* by the confound, not
flattered by it.

**One published reading is withdrawn.** The confounded pair moved the *sign* layer +6.1 on both
models and that was reported as part of the lookup signature. **In the clean pair the sign layer
does not move together at all** (gemma −3.0, qwen7b +6.1). It was coincidence. **Only the brand
layer's +7.5 survives on both** — which makes the signature narrower and stronger, not weaker.


## 1. The result

| candidate | baseline | with the brand crib | delta |
|---|---|---|---|
| `gemma2:2b` | 142/200 · **71.0%** | 147/200 · **73.5%** | **+5 rows / +2.5 pt** |
| `qwen2.5:7b-instruct-q4_K_M` | 144/200 · **72.0%** | 151/200 · **75.5%** | **+7 rows / +3.5 pt** |

**Both moves are inside D82's ±6.5 band, so neither is a resolvable lift on this set.** They are
reported as measured and must not be quoted as an improvement in the model.

## 2. Where the movement is — and it is exactly where the crib is

| layer | gemma | qwen7b |
|---|---|---|
| sign 招牌 (33) | 63.6% → 60.6% (−3.0) | 66.7% → 72.7% (+6.1) |
| brand 品牌 (40) | 87.5% → **95.0%** (+7.5) | 90.0% → **97.5%** (+7.5) |
| registered 登記 (127) | 67.7% → 70.1% (+2.4) | 67.7% → 69.3% (+1.6) |

**The brand layer moves +7.5 on both models — the identical delta, on two models that share
nothing but the crib, and the same delta the confounded pair produced.** A model-independent,
layer-specific gain is what a lookup looks like, and this is the one layer where a brand name is
the whole string. **The other two layers move in different directions on the two models and are
noise** — the sign layer's apparent agreement in the confounded pair did not survive the re-run,
which is why it is not claimed here.

## 3. Row by row: what was fixed, what broke

| | gemma | qwen7b |
|---|---|---|
| misses that became right | 10 | 10 |
| rows that were right and broke | 5 | 3 |
| **net** | **+5** | **+7** |

**Of the 8 misses whose name carries a D77 brand, gemma fixed 5 and qwen7b 6** — rows 0
`Q Burger松山南京五店`, 70 `麥味登`, 78 `CAMA`, 105 `味亦美` in both, plus 79
`Krispy Kreme Doughnuts` (gemma) and 48 `COMEBUY-松山機場門市` · 103 `五桐號` (qwen7b). **That is
the mechanism, confirmed on the clean pair.**

**The breakage is real and is the cost, and it is smaller than the confounded pair suggested** —
five rows for gemma, three for qwen7b. Adding 288 rows to a 179-row crib changes the neighbours of
every one of the 200: the `法人` share of the retrievable store falls from **25.7% (46 of 179) to
12.0% (56 of 467)**, and a `法人` row drifting to `其他` is a break in both models' lists.

**One break is not noise and needs the owner: row 20, `萬家福`, broke in BOTH models — 其他 → 法人.**
It broke *because the crib is right*: 萬家福 is one of the ten supermarkets the owner ruled to
`法人` under prompt rule 0, and `testset_v3`'s gold for that row is `其他`. **The ruling and the
frozen set disagree, and the crib made the disagreement visible.** Nothing here resolves it —
either the gold row is amended or the supermarket rows are, and both are the owner's.

## 4. What the crib is, exactly

| | |
|---|---|
| before | 179 rows (`testset`), arctic, sha `84aafea32c47` |
| after | 179 `testset` + **288 `brand`**, arctic, brand sha **`c66604f13274`** |
| labels | `claude-opus-5[1m]+gemini-3.5-flash-lite+owner` — two drafts, all 34 disagreements ruled by the owner |
| basis | each row names the `brand_registration` company it was published under |

The two drafts agreed on **254 of 288 (88.2%)**.

## 5. Two limits of the source, measured before the round

1. **D77's list carries 8 of the 20 chain misses. Ten of the twenty are not in it at all** —
   鬍鬚張 · 樂雅樂 · 點水樓 · はま寿司 · 八方雲集 · 大心 · 築間 · 美又美 · 紅屋 · 樂尼尼. They are
   not obscure; they are simply not on that publisher's list. **So this ticket could never have
   fixed more than half of the chain problem, and the other half needs an authored table.**
2. **The list contains no 火鍋, no 燒烤 and no 台菜 brand — zero of each.** A crib grown from it
   cannot help those three values. Asserted by test, so a future publication that adds one makes
   the test fail and this line come out.

## 6. The ceilings, stated before the round and held

| how the crib can be reached | rows of 58 | points |
|---|---|---|
| the D77 company join (what retrieval does **not** use) | 6 | +3.0 |
| by name, string match over all 288 | **8** | +4.0 |
| by name, plus cosine | ≤10 | ≤+5.0 |

Measured outcome on the clean pair: **gemma flipped 5 of the 8, qwen7b 6.** Both nets (+5, +7)
sit inside the by-name ceiling of 8, and both models fixed 10 rows in total — so about half of
each model's gain is the crib being read and the other half is neighbourhood movement, which is
not repeatable and should not be banked. The confounded pair's qwen7b +8 exceeded this ceiling;
the clean one does not, which is the shape a real effect should have.

## 7. Provenance

Round files carry the crib's identity in `rag` (rows per source and a digest per source), added for
this run so a report's claim can be checked against the store it was made from. Baseline files are
`round_<candidate>_v7-rag-2026-08-30_arctic.json`; this run is the `_brandcrib` suffix.
