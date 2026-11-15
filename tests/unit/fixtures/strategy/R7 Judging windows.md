# R7: Judging windows

Sample for tests (columns exactly as the R7 prompt asks; values are placeholders, not findings).

| post_type | ignore_before_hours | provisional_hours | provisional_weight | final_hours | best_early_metric | evidence | confidence | sources | how to verify |
|---|---|---|---|---|---|---|---|---|---|
| reel | 24 | 48 | 0.4 | 7 d | skip rate, it settles first | measured | medium | https://example.org/accumulation | compare 48 h with 7 d after 20 posts |
| trial_reel | 24 | 72 | 0.5 | 168 | skip rate vs other trials | observed | low | https://example.org/trials | compare trials only with trials |
| carousel | 48 | 72 | 0.5 | 7 days | saves per reach | opinion | low | https://example.org/carousels | compare 72 h with 7 d |
| image | 48 | 72 | 0.6 | 168 | reach | opinion | low | https://example.org/images | compare 72 h with 7 d |
| story | 0 | 4 | 0.5 | 30 | reach | official | high | https://example.org/stories | pull before expiry |

## Metric-specific exceptions

| post_type | metric | ignore_before_hours | provisional_hours | provisional_weight | final_hours | best_early_metric | evidence | confidence | sources | how to verify |
|---|---|---|---|---|---|---|---|---|---|---|
| reel | saves | 72 | 168 | 1 | 7 d | saves | observed | low | https://example.org/saves | compare 72 h saves with 7 d |
| carousel | shares | 72 | 168 | 1 | 168 | shares | opinion | low | https://example.org/sends | compare |
