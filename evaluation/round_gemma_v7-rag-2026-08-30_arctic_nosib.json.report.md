# Evaluation round — gemma

- **candidate**: `gemma`
- **model**: `gemma2:2b`
- **prompt version**: `v7-rag-2026-08-30_nosib`
- **retrieval (D88)**: `snowflake-arctic-embed2`, k=5
- **started / finished**: 2026-09-15T02:56:16+00:00 → 2026-09-15T02:59:54+00:00
- **test set**: `testset_v3.json`
- **test set sha256**: `84aafea32c479ad182eece68e71c37ce03d667520909a7aff1056cbb0783d868`
- **scored**: 200 rows

Two reports compare only when the sha256 above matches. A refusal or an answer outside D38's list counts as wrong and lands in the `無效` column.

## Accuracy by name layer (D82: this one first)

| layer           |   n | correct | accuracy |
|:----------------|----:|--------:|---------:|
| sign 招牌       |  33 |      18 |    54.5% |
| brand 品牌      |  40 |      29 |    72.5% |
| registered 登記 | 127 |      67 |    52.8% |

## Pooled (second, and never on its own)

| set           |   n | correct | accuracy |
|:--------------|----:|--------:|---------:|
| all layers    | 200 |     114 |    57.0% |
| of which 無效 | 200 |       8 |     4.0% |

## Accuracy by gold label

| gold     |  n | correct |          accuracy |
|:---------|---:|--------:|------------------:|
| 麵食     |  9 |       3 |             33.3% |
| 飯食     |  7 |       3 |             42.9% |
| 小吃     | 27 |      14 |             51.9% |
| 火鍋     |  3 |       2 | insufficient rows |
| 燒烤     |  5 |       2 |             40.0% |
| 日式     |  4 |       0 | insufficient rows |
| 西式     | 12 |       0 |              0.0% |
| 早餐     |  9 |       6 |             66.7% |
| 咖啡飲料 | 21 |      13 |             61.9% |
| 便利商店 | 18 |      18 |            100.0% |
| 素食     |  1 |       1 | insufficient rows |
| 其他     | 38 |      32 |             84.2% |
| 法人     | 46 |      20 |             43.5% |

## Confusion — gold down, answered across

| gold ＼ answered | 麵食 | 飯食 | 小吃 | 火鍋 | 燒烤 | 日式 | 西式 | 早餐 | 咖啡飲料 | 便利商店 | 素食 | 其他 | 法人 | 台菜 | 無效 |
|:-----------------|-----:|-----:|-----:|-----:|-----:|-----:|-----:|-----:|---------:|---------:|-----:|-----:|-----:|-----:|-----:|
| 麵食             |    3 |      |    1 |      |      |      |      |      |          |          |      |    5 |      |      |      |
| 飯食             |      |    3 |      |      |      |      |      |      |          |          |      |    3 |      |      |    1 |
| 小吃             |      |      |   14 |      |    1 |      |      |      |          |          |    1 |   11 |      |      |      |
| 火鍋             |      |      |      |    2 |      |      |      |      |          |          |      |    1 |      |      |      |
| 燒烤             |      |      |      |      |    2 |      |      |      |          |          |      |    3 |      |      |      |
| 日式             |      |      |      |      |    1 |      |      |      |          |          |      |    3 |      |      |      |
| 西式             |      |      |      |      |      |      |      |      |          |          |      |    6 |      |      |    6 |
| 早餐             |      |      |      |      |      |      |      |    6 |          |          |      |    2 |      |      |    1 |
| 咖啡飲料         |      |      |      |      |      |      |      |      |       13 |        1 |      |    6 |    1 |      |      |
| 便利商店         |      |      |      |      |      |      |      |      |          |       18 |      |      |      |      |      |
| 素食             |      |      |      |      |      |      |      |      |          |          |    1 |      |      |      |      |
| 其他             |      |    1 |      |      |      |      |      |      |        2 |          |      |   32 |    2 |    1 |      |
| 法人             |      |      |      |      |      |      |      |      |          |        1 |      |   25 |   20 |      |      |

