# Evaluation round — qwen7b

- **candidate**: `qwen7b`
- **model**: `qwen2.5:7b-instruct-q4_K_M`
- **prompt version**: `v7-2026-08-30`
- **started / finished**: 2026-09-15T02:39:46+00:00 → 2026-09-15T02:41:28+00:00
- **test set**: `testset_v3.json`
- **test set sha256**: `84aafea32c479ad182eece68e71c37ce03d667520909a7aff1056cbb0783d868`
- **scored**: 200 rows

Two reports compare only when the sha256 above matches. A refusal or an answer outside D38's list counts as wrong and lands in the `無效` column.

## Accuracy by name layer (D82: this one first)

| layer           |   n | correct | accuracy |
|:----------------|----:|--------:|---------:|
| sign 招牌       |  33 |      16 |    48.5% |
| brand 品牌      |  40 |      31 |    77.5% |
| registered 登記 | 127 |      79 |    62.2% |

## Pooled (second, and never on its own)

| set           |   n | correct | accuracy |
|:--------------|----:|--------:|---------:|
| all layers    | 200 |     126 |    63.0% |
| of which 無效 | 200 |       5 |     2.5% |

## Accuracy by gold label

| gold     |  n | correct |          accuracy |
|:---------|---:|--------:|------------------:|
| 麵食     |  9 |       3 |             33.3% |
| 飯食     |  7 |       1 |             14.3% |
| 小吃     | 27 |      12 |             44.4% |
| 火鍋     |  3 |       2 | insufficient rows |
| 燒烤     |  5 |       0 |              0.0% |
| 日式     |  4 |       3 | insufficient rows |
| 西式     | 12 |       1 |              8.3% |
| 早餐     |  9 |       4 |             44.4% |
| 咖啡飲料 | 21 |      14 |             66.7% |
| 便利商店 | 18 |      18 |            100.0% |
| 素食     |  1 |       1 | insufficient rows |
| 其他     | 38 |      24 |             63.2% |
| 法人     | 46 |      43 |             93.5% |

## Confusion — gold down, answered across

| gold ＼ answered | 麵食 | 飯食 | 小吃 | 火鍋 | 燒烤 | 日式 | 西式 | 早餐 | 咖啡飲料 | 便利商店 | 素食 | 其他 | 法人 | 台菜 | 無效 |
|:-----------------|-----:|-----:|-----:|-----:|-----:|-----:|-----:|-----:|---------:|---------:|-----:|-----:|-----:|-----:|-----:|
| 麵食             |    3 |    1 |    1 |      |      |    1 |      |      |          |          |      |      |    1 |    2 |      |
| 飯食             |    1 |    1 |      |      |      |    1 |      |      |        1 |          |      |    1 |    1 |      |    1 |
| 小吃             |      |      |   12 |      |    2 |      |      |      |          |          |    1 |   11 |      |      |    1 |
| 火鍋             |      |      |      |    2 |      |    1 |      |      |          |          |      |      |      |      |      |
| 燒烤             |      |      |      |      |      |      |      |      |          |          |      |    4 |      |      |    1 |
| 日式             |      |      |      |      |      |    3 |      |      |          |          |      |    1 |      |      |      |
| 西式             |      |      |      |      |      |      |    1 |      |          |          |      |    8 |    2 |      |    1 |
| 早餐             |      |      |      |      |      |      |      |    4 |          |          |      |    5 |      |      |      |
| 咖啡飲料         |      |      |    1 |      |      |      |      |      |       14 |          |      |    5 |    1 |      |      |
| 便利商店         |      |      |      |      |      |      |      |      |          |       18 |      |      |      |      |      |
| 素食             |      |      |      |      |      |      |      |      |          |          |    1 |      |      |      |      |
| 其他             |      |    1 |      |      |      |      |      |      |        1 |          |      |   24 |    3 |    8 |    1 |
| 法人             |      |      |      |      |      |      |      |      |          |          |    1 |    2 |   43 |      |      |

