# Evaluation round — qwen

- **candidate**: `qwen`
- **model**: `qwen2.5:3b-instruct-q4_K_M`
- **prompt version**: `v7-rag-2026-08-30`
- **retrieval (D88)**: `snowflake-arctic-embed2`, k=5
- **started / finished**: 2026-08-30T15:38:25+00:00 → 2026-08-30T15:45:54+00:00
- **test set**: `testset_v3.json`
- **test set sha256**: `84aafea32c479ad182eece68e71c37ce03d667520909a7aff1056cbb0783d868`
- **scored**: 200 rows

Two reports compare only when the sha256 above matches. A refusal or an answer outside D38's list counts as wrong and lands in the `無效` column.

## Accuracy by name layer (D82: this one first)

| layer           |   n | correct | accuracy |
|:----------------|----:|--------:|---------:|
| sign 招牌       |  33 |      14 |    42.4% |
| brand 品牌      |  40 |      33 |    82.5% |
| registered 登記 | 127 |      84 |    66.1% |

## Pooled (second, and never on its own)

| set           |   n | correct | accuracy |
|:--------------|----:|--------:|---------:|
| all layers    | 200 |     131 |    65.5% |
| of which 無效 | 200 |       5 |     2.5% |

## Accuracy by gold label

| gold     |  n | correct |          accuracy |
|:---------|---:|--------:|------------------:|
| 麵食     |  9 |       2 |             22.2% |
| 飯食     |  7 |       1 |             14.3% |
| 小吃     | 27 |      13 |             48.1% |
| 火鍋     |  3 |       2 | insufficient rows |
| 燒烤     |  5 |       3 |             60.0% |
| 日式     |  4 |       1 | insufficient rows |
| 西式     | 12 |       8 |             66.7% |
| 早餐     |  9 |       4 |             44.4% |
| 咖啡飲料 | 21 |      16 |             76.2% |
| 便利商店 | 18 |      18 |            100.0% |
| 素食     |  1 |       1 | insufficient rows |
| 其他     | 38 |      18 |             47.4% |
| 法人     | 46 |      44 |             95.7% |

## Confusion — gold down, answered across

| gold ＼ answered | 麵食 | 飯食 | 小吃 | 火鍋 | 燒烤 | 日式 | 西式 | 早餐 | 咖啡飲料 | 便利商店 | 素食 | 其他 | 法人 | 無效 |
|:-----------------|-----:|-----:|-----:|-----:|-----:|-----:|-----:|-----:|---------:|---------:|-----:|-----:|-----:|-----:|
| 麵食             |    2 |      |    1 |      |      |    1 |      |      |        1 |          |      |    2 |    2 |      |
| 飯食             |      |    1 |      |      |      |    1 |    1 |      |          |          |      |    2 |    1 |    1 |
| 小吃             |      |      |   13 |      |    1 |    1 |    2 |      |        2 |          |    1 |    4 |    1 |    2 |
| 火鍋             |      |      |    1 |    2 |      |      |      |      |          |          |      |      |      |      |
| 燒烤             |      |      |      |    1 |    3 |      |      |      |          |          |      |      |    1 |      |
| 日式             |      |      |      |      |      |    1 |    3 |      |          |          |      |      |      |      |
| 西式             |      |      |      |      |      |      |    8 |      |        1 |          |      |      |    2 |    1 |
| 早餐             |      |      |      |      |      |      |    2 |    4 |          |          |      |    2 |    1 |      |
| 咖啡飲料         |      |      |      |      |      |      |      |      |       16 |        1 |      |    1 |    3 |      |
| 便利商店         |      |      |      |      |      |      |      |      |          |       18 |      |      |      |      |
| 素食             |      |      |      |      |      |      |      |      |          |          |    1 |      |      |      |
| 其他             |      |    1 |    2 |    1 |      |      |    2 |      |        2 |        1 |      |   18 |   10 |    1 |
| 法人             |    1 |      |      |      |    1 |      |      |      |          |          |      |      |   44 |      |

