# Evaluation round — qwen7b

- **candidate**: `qwen7b`
- **model**: `qwen2.5:7b-instruct-q4_K_M`
- **prompt version**: `v7-rag-2026-08-30_nosib`
- **retrieval (D88)**: `snowflake-arctic-embed2`, k=5
- **started / finished**: 2026-09-15T02:48:18+00:00 → 2026-09-15T02:51:59+00:00
- **test set**: `testset_v3.json`
- **test set sha256**: `84aafea32c479ad182eece68e71c37ce03d667520909a7aff1056cbb0783d868`
- **scored**: 200 rows

Two reports compare only when the sha256 above matches. A refusal or an answer outside D38's list counts as wrong and lands in the `無效` column.

## Accuracy by name layer (D82: this one first)

| layer           |   n | correct | accuracy |
|:----------------|----:|--------:|---------:|
| sign 招牌       |  33 |      17 |    51.5% |
| brand 品牌      |  40 |      32 |    80.0% |
| registered 登記 | 127 |      68 |    53.5% |

## Pooled (second, and never on its own)

| set           |   n | correct | accuracy |
|:--------------|----:|--------:|---------:|
| all layers    | 200 |     117 |    58.5% |
| of which 無效 | 200 |       3 |     1.5% |

## Accuracy by gold label

| gold     |  n | correct |          accuracy |
|:---------|---:|--------:|------------------:|
| 麵食     |  9 |       3 |             33.3% |
| 飯食     |  7 |       2 |             28.6% |
| 小吃     | 27 |      13 |             48.1% |
| 火鍋     |  3 |       2 | insufficient rows |
| 燒烤     |  5 |       0 |              0.0% |
| 日式     |  4 |       2 | insufficient rows |
| 西式     | 12 |       1 |              8.3% |
| 早餐     |  9 |       7 |             77.8% |
| 咖啡飲料 | 21 |      15 |             71.4% |
| 便利商店 | 18 |      18 |            100.0% |
| 素食     |  1 |       1 | insufficient rows |
| 其他     | 38 |      27 |             71.1% |
| 法人     | 46 |      26 |             56.5% |

## Confusion — gold down, answered across

| gold ＼ answered | 麵食 | 飯食 | 小吃 | 火鍋 | 燒烤 | 日式 | 西式 | 早餐 | 咖啡飲料 | 便利商店 | 素食 | 其他 | 法人 | 台菜 | 無效 |
|:-----------------|-----:|-----:|-----:|-----:|-----:|-----:|-----:|-----:|---------:|---------:|-----:|-----:|-----:|-----:|-----:|
| 麵食             |    3 |      |      |      |      |      |      |      |          |          |      |    5 |      |    1 |      |
| 飯食             |    1 |    2 |      |      |      |    1 |      |      |        1 |          |      |    1 |    1 |      |      |
| 小吃             |      |      |   13 |      |    1 |      |      |      |          |          |    1 |   12 |      |      |      |
| 火鍋             |      |      |      |    2 |      |      |      |      |          |          |      |    1 |      |      |      |
| 燒烤             |      |      |      |      |      |      |      |      |          |          |      |    2 |      |      |    3 |
| 日式             |      |      |      |      |      |    2 |      |      |          |          |      |    2 |      |      |      |
| 西式             |      |      |      |      |      |      |    1 |    6 |          |          |      |    5 |      |      |      |
| 早餐             |      |      |      |      |      |      |      |    7 |          |          |      |    2 |      |      |      |
| 咖啡飲料         |      |      |      |      |      |      |      |      |       15 |          |      |    4 |    2 |      |      |
| 便利商店         |      |      |      |      |      |      |      |      |          |       18 |      |      |      |      |      |
| 素食             |      |      |      |      |      |      |      |      |          |          |    1 |      |      |      |      |
| 其他             |      |    1 |      |      |      |      |      |      |        1 |          |    2 |   27 |    2 |    5 |      |
| 法人             |      |      |      |      |      |      |      |      |          |          |      |   20 |   26 |      |      |

