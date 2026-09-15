# Evaluation round — gemma

- **candidate**: `gemma`
- **model**: `gemma2:2b`
- **prompt version**: `v7-2026-08-30`
- **started / finished**: 2026-09-15T02:44:07+00:00 → 2026-09-15T02:47:06+00:00
- **test set**: `testset_v3.json`
- **test set sha256**: `84aafea32c479ad182eece68e71c37ce03d667520909a7aff1056cbb0783d868`
- **scored**: 200 rows

Two reports compare only when the sha256 above matches. A refusal or an answer outside D38's list counts as wrong and lands in the `無效` column.

## Accuracy by name layer (D82: this one first)

| layer           |   n | correct | accuracy |
|:----------------|----:|--------:|---------:|
| sign 招牌       |  33 |      12 |    36.4% |
| brand 品牌      |  40 |      29 |    72.5% |
| registered 登記 | 127 |      80 |    63.0% |

## Pooled (second, and never on its own)

| set           |   n | correct | accuracy |
|:--------------|----:|--------:|---------:|
| all layers    | 200 |     121 |    60.5% |
| of which 無效 | 200 |       5 |     2.5% |

## Accuracy by gold label

| gold     |  n | correct |          accuracy |
|:---------|---:|--------:|------------------:|
| 麵食     |  9 |       3 |             33.3% |
| 飯食     |  7 |       2 |             28.6% |
| 小吃     | 27 |      18 |             66.7% |
| 火鍋     |  3 |       2 | insufficient rows |
| 燒烤     |  5 |       4 |             80.0% |
| 日式     |  4 |       1 | insufficient rows |
| 西式     | 12 |       0 |              0.0% |
| 早餐     |  9 |       4 |             44.4% |
| 咖啡飲料 | 21 |      14 |             66.7% |
| 便利商店 | 18 |      18 |            100.0% |
| 素食     |  1 |       1 | insufficient rows |
| 其他     | 38 |      21 |             55.3% |
| 法人     | 46 |      33 |             71.7% |

## Confusion — gold down, answered across

| gold ＼ answered | 麵食 | 飯食 | 小吃 | 火鍋 | 燒烤 | 日式 | 西式 | 早餐 | 咖啡飲料 | 便利商店 | 素食 | 其他 | 法人 | 台菜 | 無效 |
|:-----------------|-----:|-----:|-----:|-----:|-----:|-----:|-----:|-----:|---------:|---------:|-----:|-----:|-----:|-----:|-----:|
| 麵食             |    3 |      |    1 |      |      |    1 |      |      |          |          |      |    3 |    1 |      |      |
| 飯食             |      |    2 |      |      |      |      |      |      |        1 |          |      |    4 |      |      |      |
| 小吃             |    1 |      |   18 |      |    1 |      |      |      |        1 |          |    1 |    5 |      |      |      |
| 火鍋             |      |      |      |    2 |      |    1 |      |      |          |          |      |      |      |      |      |
| 燒烤             |      |      |      |    1 |    4 |      |      |      |          |          |      |      |      |      |      |
| 日式             |      |      |      |    1 |    1 |    1 |      |      |          |          |      |    1 |      |      |      |
| 西式             |      |      |      |    1 |      |      |      |      |          |          |      |   10 |    1 |      |      |
| 早餐             |      |      |    1 |      |      |      |      |    4 |          |          |      |    4 |      |      |      |
| 咖啡飲料         |      |      |    1 |      |      |      |      |      |       14 |        1 |      |    5 |      |      |      |
| 便利商店         |      |      |      |      |      |      |      |      |          |       18 |      |      |      |      |      |
| 素食             |      |      |      |      |      |      |      |      |          |          |    1 |      |      |      |      |
| 其他             |      |      |    1 |      |      |      |      |      |        3 |          |    1 |   21 |    2 |    5 |    5 |
| 法人             |      |      |      |    1 |      |      |      |      |          |        2 |      |   10 |   33 |      |      |

