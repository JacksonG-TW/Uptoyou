# Evaluation round — qwen7b

- **candidate**: `qwen7b`
- **model**: `qwen2.5:7b-instruct-q4_K_M`
- **prompt version**: `v5-rag-2026-08-15`
- **retrieval (D88)**: `snowflake-arctic-embed2`, k=5
- **started / finished**: 2026-08-30T08:47:25+00:00 → 2026-08-30T08:55:31+00:00
- **test set**: `testset_v1.json`
- **test set sha256**: `fd711a7483fd5d8bb894d35c62654219156d1ba144a129649058084d0963b2a0`
- **scored**: 200 rows

Two reports compare only when the sha256 above matches. A refusal or an answer outside D38's list counts as wrong and lands in the `無效` column.

## Accuracy by name layer (D82: this one first)

| layer           |   n | correct | accuracy |
|:----------------|----:|--------:|---------:|
| sign 招牌       |  33 |      23 |    69.7% |
| brand 品牌      |  40 |      14 |    35.0% |
| registered 登記 | 127 |      90 |    70.9% |

## Pooled (second, and never on its own)

| set           |   n | correct | accuracy |
|:--------------|----:|--------:|---------:|
| all layers    | 200 |     127 |    63.5% |
| of which 無效 | 200 |       3 |     1.5% |

## Accuracy by gold label

| gold     |  n | correct | accuracy |
|:---------|---:|--------:|---------:|
| 麵食     |  9 |       5 |    55.6% |
| 飯食     |  7 |       1 |    14.3% |
| 小吃     | 27 |      18 |    66.7% |
| 火鍋     |  3 |       2 |    66.7% |
| 燒烤     |  5 |       3 |    60.0% |
| 日式     |  4 |       3 |    75.0% |
| 西式     | 12 |       8 |    66.7% |
| 早餐     |  9 |       5 |    55.6% |
| 咖啡飲料 | 21 |      11 |    52.4% |
| 其他     | 57 |      30 |    52.6% |
| 法人     | 46 |      41 |    89.1% |

## Confusion — gold down, answered across

| gold ＼ answered | 麵食 | 飯食 | 小吃 | 火鍋 | 燒烤 | 日式 | 西式 | 早餐 | 咖啡飲料 | 其他 | 法人 | 無效 |
|:-----------------|-----:|-----:|-----:|-----:|-----:|-----:|-----:|-----:|---------:|-----:|-----:|-----:|
| 麵食             |    5 |    1 |      |      |      |      |      |      |          |    2 |    1 |      |
| 飯食             |      |    1 |      |      |      |    1 |      |      |          |    4 |    1 |      |
| 小吃             |      |      |   18 |      |    2 |      |      |      |          |    7 |      |      |
| 火鍋             |      |      |      |    2 |      |    1 |      |      |          |      |      |      |
| 燒烤             |      |      |      |      |    3 |      |      |      |          |    1 |      |    1 |
| 日式             |      |      |      |      |      |    3 |      |      |          |    1 |      |      |
| 西式             |      |      |      |      |      |      |    8 |      |          |    1 |    2 |    1 |
| 早餐             |      |      |      |      |      |      |    1 |    5 |          |    3 |      |      |
| 咖啡飲料         |      |      |    1 |      |      |      |      |      |       11 |    9 |      |      |
| 其他             |      |    1 |      |      |      |      |    3 |      |        2 |   30 |   20 |    1 |
| 法人             |      |      |      |      |      |      |    1 |      |          |    4 |   41 |      |

