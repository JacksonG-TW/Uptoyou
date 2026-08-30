# Evaluation round — llama

- **candidate**: `llama`
- **model**: `llama3.2:3b`
- **prompt version**: `v7-rag-2026-08-30`
- **retrieval (D88)**: `snowflake-arctic-embed2`, k=5
- **started / finished**: 2026-08-30T15:26:37+00:00 → 2026-08-30T15:35:35+00:00
- **test set**: `testset_v3.json`
- **test set sha256**: `84aafea32c479ad182eece68e71c37ce03d667520909a7aff1056cbb0783d868`
- **scored**: 200 rows

Two reports compare only when the sha256 above matches. A refusal or an answer outside D38's list counts as wrong and lands in the `無效` column.

## Accuracy by name layer (D82: this one first)

| layer           |   n | correct | accuracy |
|:----------------|----:|--------:|---------:|
| sign 招牌       |  33 |      20 |    60.6% |
| brand 品牌      |  40 |      34 |    85.0% |
| registered 登記 | 127 |      87 |    68.5% |

## Pooled (second, and never on its own)

| set           |   n | correct | accuracy |
|:--------------|----:|--------:|---------:|
| all layers    | 200 |     141 |    70.5% |
| of which 無效 | 200 |       0 |     0.0% |

## Accuracy by gold label

| gold     |  n | correct |          accuracy |
|:---------|---:|--------:|------------------:|
| 麵食     |  9 |       2 |             22.2% |
| 飯食     |  7 |       1 |             14.3% |
| 小吃     | 27 |      16 |             59.3% |
| 火鍋     |  3 |       2 | insufficient rows |
| 燒烤     |  5 |       3 |             60.0% |
| 日式     |  4 |       1 | insufficient rows |
| 西式     | 12 |       6 |             50.0% |
| 早餐     |  9 |       5 |             55.6% |
| 咖啡飲料 | 21 |      12 |             57.1% |
| 便利商店 | 18 |      18 |            100.0% |
| 素食     |  1 |       1 | insufficient rows |
| 其他     | 38 |      31 |             81.6% |
| 法人     | 46 |      43 |             93.5% |

## Confusion — gold down, answered across

| gold ＼ answered | 麵食 | 飯食 | 小吃 | 火鍋 | 燒烤 | 日式 | 西式 | 早餐 | 咖啡飲料 | 便利商店 | 素食 | 其他 | 法人 | 無效 |
|:-----------------|-----:|-----:|-----:|-----:|-----:|-----:|-----:|-----:|---------:|---------:|-----:|-----:|-----:|-----:|
| 麵食             |    2 |    1 |    1 |      |      |      |      |      |        1 |          |      |    3 |    1 |      |
| 飯食             |    2 |    1 |      |      |      |      |      |      |        1 |          |      |    2 |    1 |      |
| 小吃             |      |      |   16 |      |      |      |      |      |        1 |          |    1 |    7 |    2 |      |
| 火鍋             |      |      |      |    2 |      |      |      |      |          |          |      |    1 |      |      |
| 燒烤             |      |      |    1 |      |    3 |      |      |      |          |          |      |    1 |      |      |
| 日式             |      |      |    1 |      |      |    1 |      |      |          |          |      |    1 |    1 |      |
| 西式             |      |      |      |      |      |      |    6 |    1 |          |          |      |    2 |    3 |      |
| 早餐             |    1 |      |    1 |      |      |      |    1 |    5 |          |          |      |    1 |      |      |
| 咖啡飲料         |      |      |      |      |      |      |      |      |       12 |          |      |    7 |    2 |      |
| 便利商店         |      |      |      |      |      |      |      |      |          |       18 |      |      |      |      |
| 素食             |      |      |      |      |      |      |      |      |          |          |    1 |      |      |      |
| 其他             |    2 |      |    2 |      |      |      |      |      |        1 |          |      |   31 |    2 |      |
| 法人             |      |      |    1 |      |      |      |      |      |          |          |      |    2 |   43 |      |

