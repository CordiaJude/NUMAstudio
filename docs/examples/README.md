# Examples

Sample data files in the exact shape the scripts write, for reading the contracts in
[docs/CONTRACTS.md](../CONTRACTS.md) against something concrete. All values are synthetic: no real
NUMA account data, media ids or member information.

| File | Written by | What it shows |
|---|---|---|
| `metrics.example.json` | `metrics.py` (`STATE/metrics.json` at run time) | The Instagram metrics store after four reels and a week of account insights |
| `people.example.json` | the owners' setup answers, entered by hand (`STATE/people.json` at run time; private, never committed) | The people and consent file's shape (`schemas/people.schema.json`), with placeholder names only |

## metrics.example.json

Generated, not hand-written: `metrics.py` was run on synthetic Graph API payloads in the
Composio-wrapped shape of `INSTAGRAM_GET_IG_MEDIA_INSIGHTS` and `INSTAGRAM_GET_USER_INSIGHTS`
(`data[].name` with `values[].value` or `total_value.value`):

```
metrics.py ingest  --store metrics.json --reel MEDIA_ID --pull 48h|72h|7d --data insights.json --tags tags.json --pulled-at ISO
metrics.py account --store metrics.json --data user_insights.json --date 2026-11-10
metrics.py compute --store metrics.json
metrics.py validate --store metrics.json
```

What it contains:

- `reels`: four reels keyed by Instagram media id, each with NUMA's tags (config
  `instagram.tags`: length, series, pillar, hook_type, transitions, music_source, posting_time,
  trial_reel, collab, plus title, slug, media_id, permalink, thumbnail) and its pulls. The reels
  are at different stages, as on a real day: two have all three pulls (48h, 72h, 7d), one has 48h
  and 72h, and one only 48h (`metrics.py due --now 2026-11-12T22:00:00-06:00` lists its 72h pull).
- Each pull: `pulled_at`, the raw `metrics` under store names (Graph `saved` becomes `saves`,
  `ig_reels_avg_watch_time` becomes `avg_watch_time_ms`, `reels_skip_rate` becomes `skip_rate`)
  and the pull's `computed` values.
- Each reel's `computed`: retention, sends and saves per 1,000 reached, skip rate against the
  median of NUMA's reels, and `from_pull` (the latest pull: 7d, else 72h, else 48h).
- `account.daily`: a week of daily reach and new followers, dated by the start of each day
  (Graph's `end_time` minus one day). `account.totals`: one day's `total_value` metrics.

Try it:

```
S=skills/numa-reel-editor/scripts
python3 $S/metrics.py validate --store docs/examples/metrics.example.json
python3 $S/metrics.py compute --store docs/examples/metrics.example.json --json
python3 $S/dashboard.py docs/examples/metrics.example.json /tmp/dashboard.html --today 2026-11-12
```

`compute` rewrites the computed values in place; on this file the result is byte-identical.
