# Evaluation round — llama

- **candidate**: `llama`
- **model**: `llama3.2:3b`
- **prompt version**: `v6-rag-2026-08-30`
- **retrieval (D88)**: `snowflake-arctic-embed2`, k=5
- **started / finished**: 2026-08-30T09:44:41+00:00 → 2026-08-30T10:12:11+00:00
- **test set**: `testset_v2.json`
- **test set sha256**: `2c84384cf206c58084925598d84734e5b64c7c9fd7edd4ffb6aaf2f08db768aa`
- **scored**: 200 rows

Two reports compare only when the sha256 above matches. A refusal or an answer outside D38's list counts as wrong and lands in the `無效` column.

## Accuracy by name layer (D82: this one first)

| layer           |   n | correct | accuracy |
|:----------------|----:|--------:|---------:|
| sign 招牌       |  33 |      19 |    57.6% |
| brand 品牌      |  40 |      26 |    65.0% |
| registered 登記 | 127 |      81 |    63.8% |

## Pooled (second, and never on its own)

| set           |   n | correct | accuracy |
|:--------------|----:|--------:|---------:|
| all layers    | 200 |     126 |    63.0% |
| of which 無效 | 200 |       6 |     3.0% |

## Accuracy by gold label

| gold     |  n | correct | accuracy |
|:---------|---:|--------:|---------:|
| 麵食     |  9 |       2 |    22.2% |
| 飯食     |  7 |       1 |    14.3% |
| 小吃     | 27 |      19 |    70.4% |
| 火鍋     |  3 |       2 |    66.7% |
| 燒烤     |  5 |       1 |    20.0% |
| 日式     |  4 |       1 |    25.0% |
| 西式     | 12 |       6 |    50.0% |
| 早餐     |  9 |       5 |    55.6% |
| 咖啡飲料 | 21 |       8 |    38.1% |
| 便利商店 | 18 |      12 |    66.7% |
| 其他     | 39 |      29 |    74.4% |
| 法人     | 46 |      40 |    87.0% |

## Confusion — gold down, answered across

| gold ＼ answered | 麵食 | 飯食 | 小吃 | 火鍋 | 燒烤 | 日式 | 西式 | 早餐 | 咖啡飲料 | 便利商店 | 其他 | 法人 | 無效 |
|:-----------------|-----:|-----:|-----:|-----:|-----:|-----:|-----:|-----:|---------:|---------:|-----:|-----:|-----:|
| 麵食             |    2 |    1 |    1 |      |      |      |      |      |        1 |          |    2 |    2 |      |
| 飯食             |    2 |    1 |      |      |      |      |      |      |          |          |    3 |    1 |      |
| 小吃             |      |      |   19 |      |      |      |      |      |          |          |    8 |      |      |
| 火鍋             |      |      |      |    2 |      |      |      |      |          |          |    1 |      |      |
| 燒烤             |      |      |    1 |      |    1 |      |      |      |          |          |    2 |    1 |      |
| 日式             |      |      |    1 |      |      |    1 |      |      |          |          |      |    2 |      |
| 西式             |      |      |      |      |      |      |    6 |    1 |          |          |    1 |    4 |      |
| 早餐             |    2 |      |      |      |      |      |    1 |    5 |          |          |    1 |      |      |
| 咖啡飲料         |      |      |      |      |      |      |      |      |        8 |          |   10 |    3 |      |
| 便利商店         |      |      |      |      |      |      |      |      |          |       12 |      |      |    6 |
| 其他             |    4 |      |    4 |      |      |      |      |      |          |          |   29 |    2 |      |
| 法人             |    1 |      |    2 |      |      |      |      |      |          |          |    3 |   40 |      |

