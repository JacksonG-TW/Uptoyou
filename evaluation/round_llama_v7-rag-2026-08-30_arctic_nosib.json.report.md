# Evaluation round — llama

- **candidate**: `llama`
- **model**: `llama3.2:3b`
- **prompt version**: `v7-rag-2026-08-30_nosib`
- **retrieval (D88)**: `snowflake-arctic-embed2`, k=5
- **started / finished**: 2026-09-15T02:52:26+00:00 → 2026-09-15T02:55:49+00:00
- **test set**: `testset_v3.json`
- **test set sha256**: `84aafea32c479ad182eece68e71c37ce03d667520909a7aff1056cbb0783d868`
- **scored**: 200 rows

Two reports compare only when the sha256 above matches. A refusal or an answer outside D38's list counts as wrong and lands in the `無效` column.

## Accuracy by name layer (D82: this one first)

| layer           |   n | correct | accuracy |
|:----------------|----:|--------:|---------:|
| sign 招牌       |  33 |      13 |    39.4% |
| brand 品牌      |  40 |      24 |    60.0% |
| registered 登記 | 127 |      66 |    52.0% |

## Pooled (second, and never on its own)

| set           |   n | correct | accuracy |
|:--------------|----:|--------:|---------:|
| all layers    | 200 |     103 |    51.5% |
| of which 無效 | 200 |       0 |     0.0% |

## Accuracy by gold label

| gold     |  n | correct |          accuracy |
|:---------|---:|--------:|------------------:|
| 麵食     |  9 |       4 |             44.4% |
| 飯食     |  7 |       2 |             28.6% |
| 小吃     | 27 |       5 |             18.5% |
| 火鍋     |  3 |       1 | insufficient rows |
| 燒烤     |  5 |       0 |              0.0% |
| 日式     |  4 |       0 | insufficient rows |
| 西式     | 12 |       0 |              0.0% |
| 早餐     |  9 |       4 |             44.4% |
| 咖啡飲料 | 21 |      13 |             61.9% |
| 便利商店 | 18 |      12 |             66.7% |
| 素食     |  1 |       1 | insufficient rows |
| 其他     | 38 |      27 |             71.1% |
| 法人     | 46 |      34 |             73.9% |

## Confusion — gold down, answered across

| gold ＼ answered | 麵食 | 飯食 | 小吃 | 火鍋 | 燒烤 | 日式 | 西式 | 早餐 | 咖啡飲料 | 便利商店 | 素食 | 其他 | 法人 | 無效 |
|:-----------------|-----:|-----:|-----:|-----:|-----:|-----:|-----:|-----:|---------:|---------:|-----:|-----:|-----:|-----:|
| 麵食             |    4 |      |      |      |      |      |      |      |        1 |          |      |    4 |      |      |
| 飯食             |    3 |    2 |      |      |      |      |      |      |          |          |      |    2 |      |      |
| 小吃             |    3 |      |    5 |      |      |      |      |      |          |          |      |   17 |    2 |      |
| 火鍋             |    1 |      |      |    1 |      |      |      |      |          |          |      |    1 |      |      |
| 燒烤             |      |      |      |      |      |      |      |      |          |          |      |    3 |    2 |      |
| 日式             |    2 |      |      |      |      |      |      |      |          |          |      |    1 |    1 |      |
| 西式             |    1 |      |      |      |      |      |      |    5 |          |          |      |    3 |    3 |      |
| 早餐             |    1 |      |      |      |      |      |      |    4 |          |          |      |    4 |      |      |
| 咖啡飲料         |      |      |      |      |      |      |      |      |       13 |          |      |    6 |    2 |      |
| 便利商店         |      |      |      |      |      |      |      |      |          |       12 |      |      |    6 |      |
| 素食             |      |      |      |      |      |      |      |      |          |          |    1 |      |      |      |
| 其他             |    3 |    1 |      |      |      |      |      |    1 |        2 |        1 |      |   27 |    3 |      |
| 法人             |      |      |      |      |      |      |      |      |          |          |      |   12 |   34 |      |

