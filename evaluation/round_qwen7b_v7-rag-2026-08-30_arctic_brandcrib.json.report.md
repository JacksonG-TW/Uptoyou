# Evaluation round — qwen7b

- **candidate**: `qwen7b`
- **model**: `qwen2.5:7b-instruct-q4_K_M`
- **prompt version**: `v7-rag-2026-08-30`
- **retrieval (D88)**: `snowflake-arctic-embed2`, k=5
- **started / finished**: 2026-09-04T00:15:20+00:00 → 2026-09-04T00:26:34+00:00
- **test set**: `testset_v3.json`
- **test set sha256**: `84aafea32c479ad182eece68e71c37ce03d667520909a7aff1056cbb0783d868`
- **scored**: 200 rows

Two reports compare only when the sha256 above matches. A refusal or an answer outside D38's list counts as wrong and lands in the `無效` column.

## Accuracy by name layer (D82: this one first)

| layer           |   n | correct | accuracy |
|:----------------|----:|--------:|---------:|
| sign 招牌       |  33 |      24 |    72.7% |
| brand 品牌      |  40 |      39 |    97.5% |
| registered 登記 | 127 |      89 |    70.1% |

## Pooled (second, and never on its own)

| set           |   n | correct | accuracy |
|:--------------|----:|--------:|---------:|
| all layers    | 200 |     152 |    76.0% |
| of which 無效 | 200 |       3 |     1.5% |

## Accuracy by gold label

| gold     |  n | correct |          accuracy |
|:---------|---:|--------:|------------------:|
| 麵食     |  9 |       3 |             33.3% |
| 飯食     |  7 |       2 |             28.6% |
| 小吃     | 27 |      15 |             55.6% |
| 火鍋     |  3 |       2 | insufficient rows |
| 燒烤     |  5 |       3 |             60.0% |
| 日式     |  4 |       3 | insufficient rows |
| 西式     | 12 |       8 |             66.7% |
| 早餐     |  9 |       9 |            100.0% |
| 咖啡飲料 | 21 |      19 |             90.5% |
| 便利商店 | 18 |      18 |            100.0% |
| 素食     |  1 |       1 | insufficient rows |
| 其他     | 38 |      27 |             71.1% |
| 法人     | 46 |      42 |             91.3% |

## Confusion — gold down, answered across

| gold ＼ answered | 麵食 | 飯食 | 小吃 | 火鍋 | 燒烤 | 日式 | 西式 | 早餐 | 咖啡飲料 | 便利商店 | 素食 | 其他 | 法人 | 台菜 | 無效 |
|:-----------------|-----:|-----:|-----:|-----:|-----:|-----:|-----:|-----:|---------:|---------:|-----:|-----:|-----:|-----:|-----:|
| 麵食             |    3 |      |      |      |      |      |      |      |          |          |      |    4 |    1 |    1 |      |
| 飯食             |      |    2 |      |      |      |    1 |      |      |          |          |      |    3 |    1 |      |      |
| 小吃             |      |      |   15 |      |    2 |      |      |      |          |          |    1 |    8 |      |      |    1 |
| 火鍋             |      |      |      |    2 |      |    1 |      |      |          |          |      |      |      |      |      |
| 燒烤             |      |      |      |    1 |    3 |      |      |      |          |          |      |      |      |      |    1 |
| 日式             |      |      |      |      |      |    3 |      |      |          |          |      |    1 |      |      |      |
| 西式             |      |      |      |      |      |      |    8 |      |          |          |      |    1 |    2 |      |    1 |
| 早餐             |      |      |      |      |      |      |      |    9 |          |          |      |      |      |      |      |
| 咖啡飲料         |      |      |    1 |      |      |      |      |      |       19 |          |      |      |    1 |      |      |
| 便利商店         |      |      |      |      |      |      |      |      |          |       18 |      |      |      |      |      |
| 素食             |      |      |      |      |      |      |      |      |          |          |    1 |      |      |      |      |
| 其他             |      |    1 |    1 |      |      |      |    1 |      |        1 |          |      |   27 |    4 |    3 |      |
| 法人             |      |      |      |      |      |      |      |      |          |          |      |    4 |   42 |      |      |

