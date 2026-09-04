# Evaluation round — gemma

- **candidate**: `gemma`
- **model**: `gemma2:2b`
- **prompt version**: `v7-rag-2026-08-30`
- **retrieval (D88)**: `snowflake-arctic-embed2`, k=5
- **started / finished**: 2026-09-04T01:04:19+00:00 → 2026-09-04T01:13:03+00:00
- **test set**: `testset_v3.json`
- **test set sha256**: `84aafea32c479ad182eece68e71c37ce03d667520909a7aff1056cbb0783d868`
- **scored**: 200 rows

Two reports compare only when the sha256 above matches. A refusal or an answer outside D38's list counts as wrong and lands in the `無效` column.

## Accuracy by name layer (D82: this one first)

| layer           |   n | correct | accuracy |
|:----------------|----:|--------:|---------:|
| sign 招牌       |  33 |      20 |    60.6% |
| brand 品牌      |  40 |      38 |    95.0% |
| registered 登記 | 127 |      89 |    70.1% |

## Pooled (second, and never on its own)

| set           |   n | correct | accuracy |
|:--------------|----:|--------:|---------:|
| all layers    | 200 |     147 |    73.5% |
| of which 無效 | 200 |       0 |     0.0% |

## Accuracy by gold label

| gold     |  n | correct |          accuracy |
|:---------|---:|--------:|------------------:|
| 麵食     |  9 |       3 |             33.3% |
| 飯食     |  7 |       3 |             42.9% |
| 小吃     | 27 |      17 |             63.0% |
| 火鍋     |  3 |       2 | insufficient rows |
| 燒烤     |  5 |       3 |             60.0% |
| 日式     |  4 |       0 | insufficient rows |
| 西式     | 12 |       7 |             58.3% |
| 早餐     |  9 |       9 |            100.0% |
| 咖啡飲料 | 21 |      15 |             71.4% |
| 便利商店 | 18 |      18 |            100.0% |
| 素食     |  1 |       1 | insufficient rows |
| 其他     | 38 |      32 |             84.2% |
| 法人     | 46 |      37 |             80.4% |

## Confusion — gold down, answered across

| gold ＼ answered | 麵食 | 飯食 | 小吃 | 火鍋 | 燒烤 | 日式 | 西式 | 早餐 | 咖啡飲料 | 便利商店 | 素食 | 其他 | 法人 | 無效 |
|:-----------------|-----:|-----:|-----:|-----:|-----:|-----:|-----:|-----:|---------:|---------:|-----:|-----:|-----:|-----:|
| 麵食             |    3 |      |    1 |      |      |      |      |      |          |          |      |    4 |    1 |      |
| 飯食             |      |    3 |      |      |      |    1 |      |      |          |          |      |    3 |      |      |
| 小吃             |      |      |   17 |      |    1 |      |      |      |          |          |    1 |    8 |      |      |
| 火鍋             |      |      |      |    2 |      |      |      |      |          |          |      |    1 |      |      |
| 燒烤             |      |      |      |    1 |    3 |      |      |      |          |          |      |    1 |      |      |
| 日式             |      |      |      |    1 |    1 |      |      |      |          |          |      |    2 |      |      |
| 西式             |      |      |      |      |      |      |    7 |      |          |          |      |    3 |    2 |      |
| 早餐             |      |      |      |      |      |      |      |    9 |          |          |      |      |      |      |
| 咖啡飲料         |      |      |      |      |      |      |      |      |       15 |          |      |    6 |      |      |
| 便利商店         |      |      |      |      |      |      |      |      |          |       18 |      |      |      |      |
| 素食             |      |      |      |      |      |      |      |      |          |          |    1 |      |      |      |
| 其他             |      |    1 |      |      |      |      |      |      |        1 |          |      |   32 |    4 |      |
| 法人             |      |      |    2 |      |      |      |      |      |          |          |      |    7 |   37 |      |

