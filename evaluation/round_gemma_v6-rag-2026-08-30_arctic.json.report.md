# Evaluation round — gemma

- **candidate**: `gemma`
- **model**: `gemma2:2b`
- **prompt version**: `v6-rag-2026-08-30`
- **retrieval (D88)**: `snowflake-arctic-embed2`, k=5
- **started / finished**: 2026-08-30T09:44:22+00:00 → 2026-08-30T10:10:58+00:00
- **test set**: `testset_v2.json`
- **test set sha256**: `2c84384cf206c58084925598d84734e5b64c7c9fd7edd4ffb6aaf2f08db768aa`
- **scored**: 200 rows

Two reports compare only when the sha256 above matches. A refusal or an answer outside D38's list counts as wrong and lands in the `無效` column.

## Accuracy by name layer (D82: this one first)

| layer           |   n | correct | accuracy |
|:----------------|----:|--------:|---------:|
| sign 招牌       |  33 |      20 |    60.6% |
| brand 品牌      |  40 |      30 |    75.0% |
| registered 登記 | 127 |      74 |    58.3% |

## Pooled (second, and never on its own)

| set           |   n | correct | accuracy |
|:--------------|----:|--------:|---------:|
| all layers    | 200 |     124 |    62.0% |
| of which 無效 | 200 |       1 |     0.5% |

## Accuracy by gold label

| gold     |  n | correct | accuracy |
|:---------|---:|--------:|---------:|
| 麵食     |  9 |       3 |    33.3% |
| 飯食     |  7 |       1 |    14.3% |
| 小吃     | 27 |      19 |    70.4% |
| 火鍋     |  3 |       2 |    66.7% |
| 燒烤     |  5 |       3 |    60.0% |
| 日式     |  4 |       1 |    25.0% |
| 西式     | 12 |       6 |    50.0% |
| 早餐     |  9 |       6 |    66.7% |
| 咖啡飲料 | 21 |       8 |    38.1% |
| 便利商店 | 18 |      18 |   100.0% |
| 其他     | 39 |      33 |    84.6% |
| 法人     | 46 |      24 |    52.2% |

## Confusion — gold down, answered across

| gold ＼ answered | 麵食 | 飯食 | 小吃 | 火鍋 | 燒烤 | 日式 | 西式 | 早餐 | 咖啡飲料 | 便利商店 | 其他 | 法人 | 無效 |
|:-----------------|-----:|-----:|-----:|-----:|-----:|-----:|-----:|-----:|---------:|---------:|-----:|-----:|-----:|
| 麵食             |    3 |      |    1 |      |      |    1 |      |      |          |          |    3 |    1 |      |
| 飯食             |      |    1 |      |      |      |    1 |      |      |          |          |    5 |      |      |
| 小吃             |      |      |   19 |      |    1 |      |      |      |          |          |    7 |      |      |
| 火鍋             |      |      |      |    2 |      |      |      |      |          |          |    1 |      |      |
| 燒烤             |      |      |      |    1 |    3 |      |      |      |          |          |    1 |      |      |
| 日式             |      |      |      |    1 |    1 |    1 |      |      |          |          |    1 |      |      |
| 西式             |      |      |      |      |      |      |    6 |      |          |          |    5 |    1 |      |
| 早餐             |      |      |      |      |      |      |      |    6 |          |          |    2 |      |    1 |
| 咖啡飲料         |      |      |      |      |      |      |      |      |        8 |          |   13 |      |      |
| 便利商店         |      |      |      |      |      |      |      |      |          |       18 |      |      |      |
| 其他             |      |    1 |    2 |      |      |      |      |      |        1 |          |   33 |    2 |      |
| 法人             |      |      |    1 |      |    1 |      |      |      |          |          |   20 |   24 |      |

