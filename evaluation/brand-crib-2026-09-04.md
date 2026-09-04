# The brand crib — one round per candidate, against D77's 288 brand names

*Run 2026-09-04. Owner-ruled 「做」 (grow the crib) and 「縮」 (narrow D88's hold-out).
Prompt `v7-rag-2026-08-30` unchanged · `testset_v3` unchanged · arctic bare · k=5 · GPU box.*

> **「A lift here means the chain is in the crib now, not that the model got smarter.」**
> — the owner, ruled in advance of the round.

That sentence is the finding, and the layer table below is what it looks like as numbers.

## 1. The result

| candidate | baseline | with the brand crib | delta |
|---|---|---|---|
| `gemma2:2b` | 142/200 · **71.0%** | 145/200 · **72.5%** | **+3 rows / +1.5 pt** |
| `qwen2.5:7b-instruct-q4_K_M` | 144/200 · **72.0%** | 152/200 · **76.0%** | **+8 rows / +4.0 pt** |

**Both moves are inside D82's ±6.5 band, so neither is a resolvable lift on this set.** They are
reported as measured and must not be quoted as an improvement in the model.

## 2. Where the movement is — and it is exactly where the crib is

| layer | gemma | qwen7b |
|---|---|---|
| sign 招牌 (33) | 63.6% → **69.7%** (+6.1) | 66.7% → **72.7%** (+6.1) |
| brand 品牌 (40) | 87.5% → **95.0%** (+7.5) | 90.0% → **97.5%** (+7.5) |
| registered 登記 (127) | 67.7% → **66.1%** (−1.6) | 67.7% → **70.1%** (+2.4) |

**The brand layer moves +7.5 on both models and the sign layer +6.1 on both — the same deltas, on
two models that share nothing but the crib.** A model-independent, layer-specific gain is what a
lookup looks like. The registered layer, where a brand name almost never appears, moves in
opposite directions and is the noise.

## 3. Row by row: what was fixed, what broke

| | gemma | qwen7b |
|---|---|---|
| misses that became right | 12 | 13 |
| rows that were right and broke | 9 | 5 |
| **net** | **+3** | **+8** |

**Of the 8 misses whose name carries a D77 brand, 6 became right in both models** — rows
0 `Q Burger松山南京五店`, 48 `COMEBUY-松山機場門市`, 70 `麥味登`, 78 `CAMA`, 105 `味亦美`, and
79 `Krispy Kreme Doughnuts` (gemma) / 103 `五桐號` (qwen7b). **That is the mechanism, confirmed.**

**The breakage is real and is the cost.** Nine rows for gemma. Seven of the nine carry no brand at
all — adding 288 rows to a 179-row crib changes the neighbours of every one of the 200, and four
of gemma's breaks are `法人` rows that drifted to `其他` as the store's 法人 examples were diluted.

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

Measured outcome: **6 of the 8 flipped, in both models.** gemma's net was +3 because breakage ate
the rest; qwen7b's +8 exceeds the by-name ceiling because seven of its thirteen fixes were rows
carrying no brand — neighbourhood movement, not the crib being read, and therefore not repeatable.

## 7. Provenance

Round files carry the crib's identity in `rag` (rows per source and a digest per source), added for
this run so a report's claim can be checked against the store it was made from. Baseline files are
`round_<candidate>_v7-rag-2026-08-30_arctic.json`; this run is the `_brandcrib` suffix.
