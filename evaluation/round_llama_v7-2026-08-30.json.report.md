# Evaluation round — llama

- **candidate**: `llama`
- **model**: `llama3.2:3b`
- **prompt version**: `v7-2026-08-30`
- **started / finished**: 2026-09-15T02:41:47+00:00 → 2026-09-15T02:43:49+00:00
- **test set**: `testset_v3.json`
- **test set sha256**: `84aafea32c479ad182eece68e71c37ce03d667520909a7aff1056cbb0783d868`
- **scored**: 200 rows

Two reports compare only when the sha256 above matches. A refusal or an answer outside D38's list counts as wrong and lands in the `無效` column.

## Accuracy by name layer (D82: this one first)

| layer           |   n | correct | accuracy |
|:----------------|----:|--------:|---------:|
| sign 招牌       |  33 |      12 |    36.4% |
| brand 品牌      |  40 |      29 |    72.5% |
| registered 登記 | 127 |      57 |    44.9% |

## Pooled (second, and never on its own)

| set           |   n | correct | accuracy |
|:--------------|----:|--------:|---------:|
| all layers    | 200 |      98 |    49.0% |
| of which 無效 | 200 |       2 |     1.0% |

## Accuracy by gold label

| gold     |  n | correct |          accuracy |
|:---------|---:|--------:|------------------:|
| 麵食     |  9 |       2 |             22.2% |
| 飯食     |  7 |       1 |             14.3% |
| 小吃     | 27 |       0 |              0.0% |
| 火鍋     |  3 |       2 | insufficient rows |
| 燒烤     |  5 |       0 |              0.0% |
| 日式     |  4 |       1 | insufficient rows |
| 西式     | 12 |       0 |              0.0% |
| 早餐     |  9 |       1 |             11.1% |
| 咖啡飲料 | 21 |      11 |             52.4% |
| 便利商店 | 18 |      18 |            100.0% |
| 素食     |  1 |       1 | insufficient rows |
| 其他     | 38 |      27 |             71.1% |
| 法人     | 46 |      34 |             73.9% |

## Confusion — gold down, answered across

| gold ＼ answered | 麵食 | 飯食 | 小吃 | 火鍋 | 燒烤 | 日式 | 西式 | 早餐 | 咖啡飲料 | 便利商店 | 素食 | 其他 | 法人 | 無效 |
|:-----------------|-----:|-----:|-----:|-----:|-----:|-----:|-----:|-----:|---------:|---------:|-----:|-----:|-----:|-----:|
| 麵食             |    2 |      |      |      |      |      |      |      |          |          |      |    7 |      |      |
| 飯食             |    1 |    1 |      |      |      |    1 |      |      |        1 |          |      |    3 |      |      |
| 小吃             |      |      |      |      |      |      |      |      |          |          |    1 |   26 |      |      |
| 火鍋             |      |      |      |    2 |      |      |      |      |          |          |      |    1 |      |      |
| 燒烤             |      |      |      |      |      |      |      |      |          |          |      |    4 |    1 |      |
| 日式             |      |      |      |      |      |    1 |      |      |          |          |      |    3 |      |      |
| 西式             |    5 |      |      |      |      |      |      |      |          |          |      |    5 |    2 |      |
| 早餐             |      |      |      |      |      |      |      |    1 |          |          |      |    8 |      |      |
| 咖啡飲料         |      |      |      |      |      |      |      |      |       11 |          |      |    9 |    1 |      |
| 便利商店         |      |      |      |      |      |      |      |      |          |       18 |      |      |      |      |
| 素食             |      |      |      |      |      |      |      |      |          |          |    1 |      |      |      |
| 其他             |      |      |      |      |      |      |      |      |        3 |          |      |   27 |    6 |    2 |
| 法人             |      |      |      |      |      |      |      |      |          |          |      |   12 |   34 |      |

