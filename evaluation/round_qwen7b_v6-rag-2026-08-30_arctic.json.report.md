# Evaluation round — qwen7b

- **candidate**: `qwen7b`
- **model**: `qwen2.5:7b-instruct-q4_K_M`
- **prompt version**: `v6-rag-2026-08-30`
- **retrieval (D88)**: `snowflake-arctic-embed2`, k=5
- **started / finished**: 2026-08-30T09:44:55+00:00 → 2026-08-30T10:12:40+00:00
- **test set**: `testset_v2.json`
- **test set sha256**: `2c84384cf206c58084925598d84734e5b64c7c9fd7edd4ffb6aaf2f08db768aa`
- **scored**: 200 rows

Two reports compare only when the sha256 above matches. A refusal or an answer outside D38's list counts as wrong and lands in the `無效` column.

## Accuracy by name layer (D82: this one first)

| layer           |   n | correct | accuracy |
|:----------------|----:|--------:|---------:|
| sign 招牌       |  33 |      23 |    69.7% |
| brand 品牌      |  40 |      31 |    77.5% |
| registered 登記 | 127 |      91 |    71.7% |

## Pooled (second, and never on its own)

| set           |   n | correct | accuracy |
|:--------------|----:|--------:|---------:|
| all layers    | 200 |     145 |    72.5% |
| of which 無效 | 200 |       2 |     1.0% |

## Accuracy by gold label

| gold     |  n | correct | accuracy |
|:---------|---:|--------:|---------:|
| 麵食     |  9 |       5 |    55.6% |
| 飯食     |  7 |       1 |    14.3% |
| 小吃     | 27 |      18 |    66.7% |
| 火鍋     |  3 |       2 |    66.7% |
| 燒烤     |  5 |       3 |    60.0% |
| 日式     |  4 |       3 |    75.0% |
| 西式     | 12 |       8 |    66.7% |
| 早餐     |  9 |       6 |    66.7% |
| 咖啡飲料 | 21 |      11 |    52.4% |
| 便利商店 | 18 |      18 |   100.0% |
| 其他     | 39 |      30 |    76.9% |
| 法人     | 46 |      40 |    87.0% |

## Confusion — gold down, answered across

| gold ＼ answered | 麵食 | 飯食 | 小吃 | 火鍋 | 燒烤 | 日式 | 西式 | 早餐 | 咖啡飲料 | 便利商店 | 其他 | 法人 | 無效 |
|:-----------------|-----:|-----:|-----:|-----:|-----:|-----:|-----:|-----:|---------:|---------:|-----:|-----:|-----:|
| 麵食             |    5 |    1 |      |      |      |      |      |      |          |          |    2 |    1 |      |
| 飯食             |      |    1 |      |      |      |    1 |      |      |        1 |          |    3 |    1 |      |
| 小吃             |      |      |   18 |      |    2 |      |      |      |          |          |    7 |      |      |
| 火鍋             |      |      |      |    2 |      |    1 |      |      |          |          |      |      |      |
| 燒烤             |      |      |      |      |    3 |      |      |      |          |          |    1 |      |    1 |
| 日式             |      |      |      |      |      |    3 |      |      |          |          |    1 |      |      |
| 西式             |      |      |      |      |      |      |    8 |      |          |          |    1 |    2 |    1 |
| 早餐             |      |      |      |      |      |      |    1 |    6 |          |          |    2 |      |      |
| 咖啡飲料         |      |      |    1 |      |      |      |      |      |       11 |        1 |    7 |    1 |      |
| 便利商店         |      |      |      |      |      |      |      |      |          |       18 |      |      |      |
| 其他             |      |    1 |    1 |      |      |      |    3 |      |        2 |          |   30 |    2 |      |
| 法人             |    1 |      |      |      |      |      |      |      |          |          |    5 |   40 |      |

