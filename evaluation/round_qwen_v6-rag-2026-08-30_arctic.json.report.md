# Evaluation round — qwen

- **candidate**: `qwen`
- **model**: `qwen2.5:3b-instruct-q4_K_M`
- **prompt version**: `v6-rag-2026-08-30`
- **retrieval (D88)**: `snowflake-arctic-embed2`, k=5
- **started / finished**: 2026-08-30T09:35:37+00:00 → 2026-08-30T10:12:49+00:00
- **test set**: `testset_v2.json`
- **test set sha256**: `2c84384cf206c58084925598d84734e5b64c7c9fd7edd4ffb6aaf2f08db768aa`
- **scored**: 200 rows

Two reports compare only when the sha256 above matches. A refusal or an answer outside D38's list counts as wrong and lands in the `無效` column.

## Accuracy by name layer (D82: this one first)

| layer           |   n | correct | accuracy |
|:----------------|----:|--------:|---------:|
| sign 招牌       |  33 |      11 |    33.3% |
| brand 品牌      |  40 |      29 |    72.5% |
| registered 登記 | 127 |      81 |    63.8% |

## Pooled (second, and never on its own)

| set           |   n | correct | accuracy |
|:--------------|----:|--------:|---------:|
| all layers    | 200 |     121 |    60.5% |
| of which 無效 | 200 |       4 |     2.0% |

## Accuracy by gold label

| gold     |  n | correct | accuracy |
|:---------|---:|--------:|---------:|
| 麵食     |  9 |       2 |    22.2% |
| 飯食     |  7 |       1 |    14.3% |
| 小吃     | 27 |      15 |    55.6% |
| 火鍋     |  3 |       2 |    66.7% |
| 燒烤     |  5 |       4 |    80.0% |
| 日式     |  4 |       2 |    50.0% |
| 西式     | 12 |       8 |    66.7% |
| 早餐     |  9 |       4 |    44.4% |
| 咖啡飲料 | 21 |      14 |    66.7% |
| 便利商店 | 18 |      18 |   100.0% |
| 其他     | 39 |      11 |    28.2% |
| 法人     | 46 |      40 |    87.0% |

## Confusion — gold down, answered across

| gold ＼ answered | 麵食 | 飯食 | 小吃 | 火鍋 | 燒烤 | 日式 | 西式 | 早餐 | 咖啡飲料 | 便利商店 | 其他 | 法人 | 無效 |
|:-----------------|-----:|-----:|-----:|-----:|-----:|-----:|-----:|-----:|---------:|---------:|-----:|-----:|-----:|
| 麵食             |    2 |      |    1 |      |      |      |    1 |    1 |        1 |          |      |    3 |      |
| 飯食             |      |    1 |      |    1 |    1 |    1 |      |      |          |          |      |    2 |    1 |
| 小吃             |      |      |   15 |      |    1 |    1 |    2 |      |        1 |          |    6 |      |    1 |
| 火鍋             |      |      |    1 |    2 |      |      |      |      |          |          |      |      |      |
| 燒烤             |      |      |      |      |    4 |      |      |      |          |          |      |    1 |      |
| 日式             |      |      |    1 |      |      |    2 |    1 |      |          |          |      |      |      |
| 西式             |      |      |      |      |      |      |    8 |      |          |          |    1 |    2 |    1 |
| 早餐             |      |      |    1 |      |      |      |    3 |    4 |          |          |    1 |      |      |
| 咖啡飲料         |      |      |      |      |      |    1 |    1 |      |       14 |        1 |    2 |    2 |      |
| 便利商店         |      |      |      |      |      |      |      |      |          |       18 |      |      |      |
| 其他             |      |    1 |    9 |    1 |    1 |    1 |    1 |      |        3 |        1 |   11 |    9 |    1 |
| 法人             |    1 |      |    1 |      |    1 |      |      |      |          |        1 |    2 |   40 |      |

