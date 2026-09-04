# Evaluation round — gemma

- **candidate**: `gemma`
- **model**: `gemma2:2b`
- **prompt version**: `v7-rag-2026-08-30`
- **retrieval (D88)**: `snowflake-arctic-embed2`, k=5
- **started / finished**: 2026-09-04T00:04:35+00:00 → 2026-09-04T00:13:53+00:00
- **test set**: `testset_v3.json`
- **test set sha256**: `84aafea32c479ad182eece68e71c37ce03d667520909a7aff1056cbb0783d868`
- **scored**: 200 rows

Two reports compare only when the sha256 above matches. A refusal or an answer outside D38's list counts as wrong and lands in the `無效` column.

## Accuracy by name layer (D82: this one first)

| layer           |   n | correct | accuracy |
|:----------------|----:|--------:|---------:|
| sign 招牌       |  33 |      23 |    69.7% |
| brand 品牌      |  40 |      38 |    95.0% |
| registered 登記 | 127 |      84 |    66.1% |

## Pooled (second, and never on its own)

| set           |   n | correct | accuracy |
|:--------------|----:|--------:|---------:|
| all layers    | 200 |     145 |    72.5% |
| of which 無效 | 200 |       1 |     0.5% |

## Accuracy by gold label

| gold     |  n | correct |          accuracy |
|:---------|---:|--------:|------------------:|
| 麵食     |  9 |       3 |             33.3% |
| 飯食     |  7 |       3 |             42.9% |
| 小吃     | 27 |      17 |             63.0% |
| 火鍋     |  3 |       2 | insufficient rows |
| 燒烤     |  5 |       3 |             60.0% |
| 日式     |  4 |       0 | insufficient rows |
| 西式     | 12 |       6 |             50.0% |
| 早餐     |  9 |       8 |             88.9% |
| 咖啡飲料 | 21 |      16 |             76.2% |
| 便利商店 | 18 |      18 |            100.0% |
| 素食     |  1 |       1 | insufficient rows |
| 其他     | 38 |      34 |             89.5% |
| 法人     | 46 |      34 |             73.9% |

## Confusion — gold down, answered across

| gold ＼ answered | 麵食 | 飯食 | 小吃 | 火鍋 | 燒烤 | 日式 | 西式 | 早餐 | 咖啡飲料 | 便利商店 | 素食 | 其他 | 法人 | 無效 |
|:-----------------|-----:|-----:|-----:|-----:|-----:|-----:|-----:|-----:|---------:|---------:|-----:|-----:|-----:|-----:|
| 麵食             |    3 |      |    1 |      |      |      |      |      |          |          |      |    4 |    1 |      |
| 飯食             |      |    3 |      |      |      |      |      |      |          |          |      |    3 |      |    1 |
| 小吃             |      |      |   17 |      |      |      |      |      |          |          |    1 |    9 |      |      |
| 火鍋             |      |      |      |    2 |      |      |      |      |          |          |      |    1 |      |      |
| 燒烤             |      |      |      |    1 |    3 |      |      |      |          |          |      |      |    1 |      |
| 日式             |      |      |      |    1 |    1 |      |      |      |          |          |      |    2 |      |      |
| 西式             |      |      |      |      |      |      |    6 |      |          |          |      |    3 |    3 |      |
| 早餐             |      |      |      |      |      |      |      |    8 |          |          |      |    1 |      |      |
| 咖啡飲料         |      |      |      |      |      |      |      |      |       16 |          |      |    5 |      |      |
| 便利商店         |      |      |      |      |      |      |      |      |          |       18 |      |      |      |      |
| 素食             |      |      |      |      |      |      |      |      |          |          |    1 |      |      |      |
| 其他             |      |      |      |      |      |      |      |      |        1 |          |      |   34 |    3 |      |
| 法人             |      |      |    2 |      |      |      |      |      |          |          |      |   10 |   34 |      |

