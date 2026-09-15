# Evaluation round — gemma

- **candidate**: `gemma`
- **model**: `gemma2:2b`
- **prompt version**: `v7-rag-2026-08-30_boot2`
- **retrieval (D88)**: `snowflake-arctic-embed2`, k=5
- **started / finished**: 2026-09-15T08:01:59+00:00 → 2026-09-15T08:05:45+00:00
- **test set**: `testset_v3.json`
- **test set sha256**: `84aafea32c479ad182eece68e71c37ce03d667520909a7aff1056cbb0783d868`
- **scored**: 200 rows

Two reports compare only when the sha256 above matches. A refusal or an answer outside D38's list counts as wrong and lands in the `無效` column.

## Accuracy by name layer (D82: this one first)

| layer           |   n | correct | accuracy |
|:----------------|----:|--------:|---------:|
| sign 招牌       |  33 |      17 |    51.5% |
| brand 品牌      |  40 |      29 |    72.5% |
| registered 登記 | 127 |      78 |    61.4% |

## Pooled (second, and never on its own)

| set           |   n | correct | accuracy |
|:--------------|----:|--------:|---------:|
| all layers    | 200 |     124 |    62.0% |
| of which 無效 | 200 |       3 |     1.5% |

## Accuracy by gold label

| gold     |  n | correct |          accuracy |
|:---------|---:|--------:|------------------:|
| 麵食     |  9 |       3 |             33.3% |
| 飯食     |  7 |       1 |             14.3% |
| 小吃     | 27 |      14 |             51.9% |
| 火鍋     |  3 |       2 | insufficient rows |
| 燒烤     |  5 |       1 |             20.0% |
| 日式     |  4 |       0 | insufficient rows |
| 西式     | 12 |       0 |              0.0% |
| 早餐     |  9 |       3 |             33.3% |
| 咖啡飲料 | 21 |      13 |             61.9% |
| 便利商店 | 18 |      18 |            100.0% |
| 素食     |  1 |       1 | insufficient rows |
| 其他     | 38 |      32 |             84.2% |
| 法人     | 46 |      36 |             78.3% |

## Confusion — gold down, answered across

| gold ＼ answered | 麵食 | 飯食 | 小吃 | 火鍋 | 燒烤 | 日式 | 西式 | 早餐 | 咖啡飲料 | 便利商店 | 素食 | 其他 | 法人 | 無效 |
|:-----------------|-----:|-----:|-----:|-----:|-----:|-----:|-----:|-----:|---------:|---------:|-----:|-----:|-----:|-----:|
| 麵食             |    3 |      |    1 |      |      |      |      |      |          |          |      |    5 |      |      |
| 飯食             |      |    1 |      |      |      |    1 |      |      |          |          |      |    3 |    1 |    1 |
| 小吃             |      |      |   14 |      |    1 |      |      |      |          |          |    1 |   11 |      |      |
| 火鍋             |      |      |      |    2 |      |      |      |      |          |          |      |    1 |      |      |
| 燒烤             |      |      |      |    1 |    1 |      |      |      |          |          |      |    3 |      |      |
| 日式             |      |      |      |    1 |    1 |      |      |      |          |          |      |    1 |    1 |      |
| 西式             |      |      |      |      |      |      |      |      |          |          |      |   11 |    1 |      |
| 早餐             |      |      |      |      |      |      |      |    3 |          |          |      |    6 |      |      |
| 咖啡飲料         |      |      |      |      |      |      |      |      |       13 |          |      |    8 |      |      |
| 便利商店         |      |      |      |      |      |      |      |      |          |       18 |      |      |      |      |
| 素食             |      |      |      |      |      |      |      |      |          |          |    1 |      |      |      |
| 其他             |      |      |      |      |      |      |      |      |        2 |          |      |   32 |    2 |    2 |
| 法人             |      |      |      |      |      |      |      |      |          |          |      |   10 |   36 |      |

