# Evaluation round — gemma

- **candidate**: `gemma`
- **model**: `gemma2:2b`
- **prompt version**: `v7-rag-2026-08-30`
- **retrieval (D88)**: `snowflake-arctic-embed2`, k=5
- **started / finished**: 2026-08-30T15:13:24+00:00 → 2026-08-30T15:26:20+00:00
- **test set**: `testset_v3.json`
- **test set sha256**: `84aafea32c479ad182eece68e71c37ce03d667520909a7aff1056cbb0783d868`
- **scored**: 200 rows

Two reports compare only when the sha256 above matches. A refusal or an answer outside D38's list counts as wrong and lands in the `無效` column.

## Accuracy by name layer (D82: this one first)

| layer           |   n | correct | accuracy |
|:----------------|----:|--------:|---------:|
| sign 招牌       |  33 |      21 |    63.6% |
| brand 品牌      |  40 |      35 |    87.5% |
| registered 登記 | 127 |      86 |    67.7% |

## Pooled (second, and never on its own)

| set           |   n | correct | accuracy |
|:--------------|----:|--------:|---------:|
| all layers    | 200 |     142 |    71.0% |
| of which 無效 | 200 |       2 |     1.0% |

## Accuracy by gold label

| gold     |  n | correct |          accuracy |
|:---------|---:|--------:|------------------:|
| 麵食     |  9 |       3 |             33.3% |
| 飯食     |  7 |       2 |             28.6% |
| 小吃     | 27 |      17 |             63.0% |
| 火鍋     |  3 |       2 | insufficient rows |
| 燒烤     |  5 |       3 |             60.0% |
| 日式     |  4 |       0 | insufficient rows |
| 西式     | 12 |       7 |             58.3% |
| 早餐     |  9 |       4 |             44.4% |
| 咖啡飲料 | 21 |      14 |             66.7% |
| 便利商店 | 18 |      18 |            100.0% |
| 素食     |  1 |       1 | insufficient rows |
| 其他     | 38 |      33 |             86.8% |
| 法人     | 46 |      38 |             82.6% |

## Confusion — gold down, answered across

| gold ＼ answered | 麵食 | 飯食 | 小吃 | 火鍋 | 燒烤 | 日式 | 西式 | 早餐 | 咖啡飲料 | 便利商店 | 素食 | 其他 | 法人 | 無效 |
|:-----------------|-----:|-----:|-----:|-----:|-----:|-----:|-----:|-----:|---------:|---------:|-----:|-----:|-----:|-----:|
| 麵食             |    3 |      |    1 |      |      |      |      |      |          |          |      |    4 |    1 |      |
| 飯食             |      |    2 |      |      |      |      |      |      |          |          |      |    3 |    1 |    1 |
| 小吃             |      |      |   17 |      |    1 |      |      |      |          |          |    1 |    8 |      |      |
| 火鍋             |      |      |      |    2 |      |      |      |      |          |          |      |    1 |      |      |
| 燒烤             |      |      |      |    1 |    3 |      |      |      |          |          |      |    1 |      |      |
| 日式             |      |      |      |    1 |    1 |      |      |      |          |          |      |    2 |      |      |
| 西式             |      |      |      |      |      |      |    7 |      |          |          |      |    3 |    2 |      |
| 早餐             |      |      |    1 |      |      |      |      |    4 |          |          |      |    3 |      |    1 |
| 咖啡飲料         |      |      |      |      |      |      |      |      |       14 |          |      |    6 |    1 |      |
| 便利商店         |      |      |      |      |      |      |      |      |          |       18 |      |      |      |      |
| 素食             |      |      |      |      |      |      |      |      |          |          |    1 |      |      |      |
| 其他             |      |      |      |      |      |      |      |      |        2 |          |      |   33 |    3 |      |
| 法人             |      |      |    2 |      |      |      |      |      |          |          |      |    6 |   38 |      |

