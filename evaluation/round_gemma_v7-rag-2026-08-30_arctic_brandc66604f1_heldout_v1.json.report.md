# Evaluation round — gemma

- **candidate**: `gemma`
- **model**: `gemma2:2b`
- **prompt version**: `v7-rag-2026-08-30`
- **retrieval (D88)**: `snowflake-arctic-embed2`, k=5
- **started / finished**: 2026-10-11T13:34:07+00:00 → 2026-10-11T13:39:49+00:00
- **test set**: `heldout_v1.json`
- **test set sha256**: `e102b6c5a6a3a25fb05a1de73fddfcce8488ffc91e816220930ef6dfe2b26610`
- **scored**: 200 rows

Two reports compare only when the sha256 above matches. A refusal or an answer outside D38's list counts as wrong and lands in the `無效` column.

## Accuracy by name layer (D82: this one first)

| layer           |   n | correct | accuracy |
|:----------------|----:|--------:|---------:|
| sign 招牌       |  32 |      16 |    50.0% |
| brand 品牌      |  39 |      37 |    94.9% |
| registered 登記 | 129 |      98 |    76.0% |

## Pooled (second, and never on its own)

| set           |   n | correct | accuracy |
|:--------------|----:|--------:|---------:|
| all layers    | 200 |     151 |    75.5% |
| of which 無效 | 200 |       3 |     1.5% |

## Accuracy by gold label

| gold     |  n | correct |          accuracy |
|:---------|---:|--------:|------------------:|
| 麵食     | 14 |       5 |             35.7% |
| 飯食     | 13 |       5 |             38.5% |
| 小吃     | 26 |      22 |             84.6% |
| 火鍋     |  5 |       4 |             80.0% |
| 燒烤     |  3 |       2 | insufficient rows |
| 日式     |  7 |       3 |             42.9% |
| 西式     | 13 |       9 |             69.2% |
| 早餐     |  8 |       7 |             87.5% |
| 咖啡飲料 | 14 |      14 |            100.0% |
| 便利商店 | 25 |      25 |            100.0% |
| 其他     | 17 |      12 |             70.6% |
| 法人     | 55 |      43 |             78.2% |

## Confusion — gold down, answered across

| gold ＼ answered | 麵食 | 飯食 | 小吃 | 火鍋 | 燒烤 | 日式 | 西式 | 早餐 | 咖啡飲料 | 便利商店 | 其他 | 法人 | 無效 |
|:-----------------|-----:|-----:|-----:|-----:|-----:|-----:|-----:|-----:|---------:|---------:|-----:|-----:|-----:|
| 麵食             |    5 |      |    2 |      |      |      |      |      |          |          |    5 |    1 |    1 |
| 飯食             |      |    5 |    1 |    1 |      |      |      |      |          |        1 |    4 |    1 |      |
| 小吃             |    1 |      |   22 |    1 |      |      |      |      |          |          |    1 |      |    1 |
| 火鍋             |      |      |      |    4 |      |      |      |      |          |          |    1 |      |      |
| 燒烤             |      |      |      |    1 |    2 |      |      |      |          |          |      |      |      |
| 日式             |      |      |    1 |      |      |    3 |      |      |          |          |    3 |      |      |
| 西式             |      |      |      |      |      |      |    9 |      |          |          |    4 |      |      |
| 早餐             |      |      |    1 |      |      |      |      |    7 |          |          |      |      |      |
| 咖啡飲料         |      |      |      |      |      |      |      |      |       14 |          |      |      |      |
| 便利商店         |      |      |      |      |      |      |      |      |          |       25 |      |      |      |
| 其他             |      |      |      |    1 |    1 |    1 |      |      |          |          |   12 |    1 |    1 |
| 法人             |      |      |      |      |      |      |      |      |          |          |   12 |   43 |      |

