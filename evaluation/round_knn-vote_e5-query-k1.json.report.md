# Evaluation round — knn-vote

- **candidate**: `knn-vote`
- **model**: `none — majority vote of the k nearest labelled names`
- **prompt version**: `knn-vote_e5_query_k1`
- **retrieval (D88)**: `zylonai/multilingual-e5-large`, k=1
- **started / finished**: 2026-08-31T15:46:57+00:00 → 2026-08-31T15:47:03+00:00
- **test set**: `testset_v3.json`
- **test set sha256**: `84aafea32c479ad182eece68e71c37ce03d667520909a7aff1056cbb0783d868`
- **scored**: 200 rows

Two reports compare only when the sha256 above matches. A refusal or an answer outside D38's list counts as wrong and lands in the `無效` column.

## Accuracy by name layer (D82: this one first)

| layer           |   n | correct | accuracy |
|:----------------|----:|--------:|---------:|
| sign 招牌       |  33 |      14 |    42.4% |
| brand 品牌      |  40 |      25 |    62.5% |
| registered 登記 | 127 |      64 |    50.4% |

## Pooled (second, and never on its own)

| set           |   n | correct | accuracy |
|:--------------|----:|--------:|---------:|
| all layers    | 200 |     103 |    51.5% |
| of which 無效 | 200 |       0 |     0.0% |

## Accuracy by gold label

| gold     |  n | correct |          accuracy |
|:---------|---:|--------:|------------------:|
| 麵食     |  9 |       0 |              0.0% |
| 飯食     |  7 |       0 |              0.0% |
| 小吃     | 27 |      19 |             70.4% |
| 火鍋     |  3 |       1 | insufficient rows |
| 燒烤     |  5 |       2 |             40.0% |
| 日式     |  4 |       0 | insufficient rows |
| 西式     | 12 |       5 |             41.7% |
| 早餐     |  9 |       6 |             66.7% |
| 咖啡飲料 | 21 |       7 |             33.3% |
| 便利商店 | 18 |      13 |             72.2% |
| 素食     |  1 |       0 | insufficient rows |
| 其他     | 38 |      21 |             55.3% |
| 法人     | 46 |      29 |             63.0% |

## Confusion — gold down, answered across

| gold ＼ answered | 麵食 | 飯食 | 小吃 | 火鍋 | 燒烤 | 日式 | 西式 | 早餐 | 咖啡飲料 | 便利商店 | 素食 | 其他 | 法人 | 無效 |
|:-----------------|-----:|-----:|-----:|-----:|-----:|-----:|-----:|-----:|---------:|---------:|-----:|-----:|-----:|-----:|
| 麵食             |      |    1 |      |      |      |      |      |    2 |        2 |          |      |    3 |    1 |      |
| 飯食             |      |      |      |      |    2 |      |    2 |      |          |          |      |    2 |    1 |      |
| 小吃             |      |      |   19 |      |    1 |    1 |      |      |        1 |          |      |    3 |    2 |      |
| 火鍋             |      |      |      |    1 |      |      |      |      |          |          |      |    1 |    1 |      |
| 燒烤             |      |      |      |      |    2 |      |      |      |          |          |      |    2 |    1 |      |
| 日式             |      |    1 |    1 |      |    1 |      |    1 |      |          |          |      |      |      |      |
| 西式             |      |      |    1 |      |    1 |      |    5 |      |          |          |      |    1 |    4 |      |
| 早餐             |    1 |    1 |      |      |      |      |    1 |    6 |          |          |      |      |      |      |
| 咖啡飲料         |      |      |      |      |    1 |      |      |      |        7 |          |      |    8 |    5 |      |
| 便利商店         |      |      |      |      |      |      |      |      |          |       13 |      |    5 |      |      |
| 素食             |      |      |      |      |      |      |      |      |          |          |      |    1 |      |      |
| 其他             |      |    1 |    7 |    1 |    1 |      |      |      |        5 |          |      |   21 |    2 |      |
| 法人             |    7 |    1 |    2 |      |      |    1 |    3 |      |        1 |          |      |    2 |   29 |      |

