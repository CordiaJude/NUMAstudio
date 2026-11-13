"""metrics.py: metrics store, Graph insights parsing, computed metrics, pull schedule (R245-R248, R251)."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

import metrics as mx
import numa_common


def graph(**values):
    """A Composio-wrapped INSTAGRAM_GET_IG_MEDIA_INSIGHTS response."""
    data = []
    for k, v in values.items():
        if k == "shares":
            data.append({"name": k, "period": "lifetime", "total_value": {"value": v}})
        else:
            data.append({"name": k, "period": "lifetime", "values": [{"value": v}], "id": f"1/insights/{k}"})
    return {"data": {"data": data}, "successful": True, "error": None}


def run(argv):
    with pytest.raises(SystemExit) as e:
        numa_common.run_cli(mx.main, argv)
    return e.value.code


@pytest.fixture
def store(tmp_path):
    return tmp_path / "metrics.json"


def ingest(store, tmp_path, reel, pull, tags=None, **values):
    d = tmp_path / f"{reel}_{pull}.json"
    d.write_text(json.dumps(graph(**values)))
    args = ["ingest", "--store", str(store), "--reel", reel, "--pull", pull, "--data", str(d)]
    if tags is not None:
        args += ["--tags", json.dumps(tags)]
    return run(args)


def test_parse_graph_shapes(nc):
    m, ignored = mx.parse_media_insights(graph(views=100, reach=80, saved=4, shares=3, ig_reels_avg_watch_time=12000,
                                              reels_skip_rate=41.5, follows=1, navigation=2), "x")
    assert m == {"views": 100, "reach": 80, "saves": 4, "shares": 3, "avg_watch_time_ms": 12000, "skip_rate": 41.5,
                 "follows": 1}
    assert ignored == ["navigation"]
    flat, _ = mx.parse_media_insights({"views": 5, "reach": 4}, "x")
    assert flat == {"views": 5, "reach": 4}


@pytest.mark.parametrize("bad", ["plays", "impressions"])
def test_rejects_retired_metrics(nc, store, tmp_path, capsys, bad):
    assert ingest(store, tmp_path, "r1", "48h", **{"views": 10, bad: 99}) == 1
    assert "retired metric" in capsys.readouterr().err
    assert not store.exists()


def test_input_validation(nc, store, tmp_path, capsys):
    assert ingest(store, tmp_path, "r1", "48h", views=-1) == 1
    assert ingest(store, tmp_path, "r1", "48h", tags={"lenght": 30}, views=1) == 1
    assert "unknown tag" in capsys.readouterr().err
    assert ingest(store, tmp_path, "r1", "48h", tags={"trial_reel": "yes"}, views=1) == 1
    assert ingest(store, tmp_path, "r1", "48h", tags={"posting_time": "tomorrow"}, views=1) == 1
    assert run(["ingest", "--store", str(store), "--reel", "r1", "--pull", "5d", "--data", "{}"]) == 2
    assert run(["ingest", "--store", str(store), "--reel", "r1", "--pull", "48h", "--data", "{}"]) == 1


def test_computed_metrics(nc, store, tmp_path):
    tags = {"length": 30, "series": "first_plunge", "pillar": "community", "hook_type": "question",
            "transitions": ["punch", "whip"], "music_source": "higgsfield", "posting_time": "2026-11-02T17:00:00-06:00",
            "trial_reel": False, "collab": True}
    assert ingest(store, tmp_path, "r1", "48h", tags, views=900, reach=500, shares=10, saved=5,
                  ig_reels_avg_watch_time=12000, reels_skip_rate=40) == 0
    assert ingest(store, tmp_path, "r1", "7d", views=2000, reach=1000, shares=25, saved=8,
                  ig_reels_avg_watch_time=15000, reels_skip_rate=40) == 0
    assert ingest(store, tmp_path, "r2", "72h", {"length": 20}, views=500, reach=400, shares=2, saved=1,
                  ig_reels_avg_watch_time=5000, reels_skip_rate=60) == 0
    assert ingest(store, tmp_path, "r3", "72h", {"length": 45}, views=700, reach=500, shares=4, saved=2,
                  ig_reels_avg_watch_time=9000, reels_skip_rate=50) == 0
    data = json.loads(store.read_text())
    r1 = data["reels"]["r1"]
    assert list(r1["pulls"]) == ["48h", "7d"]
    assert r1["tags"]["collab"] is True and r1["tags"]["series"] == "first_plunge"
    assert r1["pulls"]["48h"]["computed"]["retention"] == pytest.approx(0.4)
    c = r1["computed"]
    assert c["from_pull"] == "7d"
    assert c["retention"] == pytest.approx(0.5)            # 15 s / 30 s
    assert c["sends_per_1k_reach"] == pytest.approx(25.0)
    assert c["saves_per_1k_reach"] == pytest.approx(8.0)
    assert c["skip_rate_median"] == 50 and c["skip_rate_vs_median"] == -10
    assert data["reels"]["r2"]["computed"]["skip_rate_vs_median"] == 10
    assert run(["validate", "--store", str(store)]) == 0


def test_account_insights_kept(nc, store, tmp_path):
    resp = {"data": [{"name": "reach", "period": "day", "values": [
        {"value": 120, "end_time": "2026-01-02T08:00:00+0000"}, {"value": 140, "end_time": "2026-01-03T08:00:00+0000"}]},
        {"name": "accounts_engaged", "period": "day", "total_value": {"value": 33}}]}
    f = tmp_path / "u.json"
    f.write_text(json.dumps(resp))
    assert run(["account", "--store", str(store), "--data", str(f)]) == 2  # total_value needs --date
    assert run(["account", "--store", str(store), "--data", str(f), "--date", "2026-01-03"]) == 0
    resp["data"][0]["values"] = [{"value": 999, "end_time": "2026-06-01T07:00:00+0000"}]
    f.write_text(json.dumps(resp))
    assert run(["account", "--store", str(store), "--data", str(f), "--date", "2026-06-01"]) == 0
    acct = json.loads(store.read_text())["account"]
    assert acct["daily"]["2026-01-01"]["reach"] == 120  # period start; older than 90 days and still there
    assert acct["daily"]["2026-05-31"]["reach"] == 999
    assert acct["totals"]["2026-01-03"]["accounts_engaged"] == 33
    f.write_text(json.dumps({"data": [{"name": "impressions", "values": [{"value": 1}]}]}))
    assert run(["account", "--store", str(store), "--data", str(f), "--date", "2026-06-02"]) == 1


def test_due_schedule(nc, store, tmp_path, capsys):
    run(["tag", "--store", str(store), "--reel", "a", "--tags", json.dumps({"posting_time": "2026-11-01T17:00:00-05:00"})])
    run(["tag", "--store", str(store), "--reel", "b", "--tags", json.dumps({"posting_time": "2026-11-04T17:00:00-06:00"})])
    ingest(store, tmp_path, "a", "48h", views=1)
    data = json.loads(store.read_text())
    now = datetime(2026, 11, 5, 0, 0, tzinfo=timezone.utc)  # a: 74 h after posting, b: 1 h
    assert mx.due(data, now) == [{"reel": "a", "post_type": "reel", "pulls": ["72h"], "pull_now": "72h", "hours_since_post": 74.0,
                                  "posting_time": "2026-11-01T17:00:00-05:00", "media_id": None}]
    later = mx.due(data, datetime(2026, 11, 12, 0, 0, tzinfo=timezone.utc))
    assert [(d["reel"], d["pull_now"]) for d in later] == [("a", "7d"), ("b", "7d")]
    capsys.readouterr()
    assert run(["due", "--store", str(store), "--now", "2026-11-05T00:00:00Z", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["reel"] == "a"


def test_naive_times_are_central(nc):
    assert mx.parse_time("2026-07-01T17:00:00", "t").utcoffset().total_seconds() == -5 * 3600
    assert mx.to_central(mx.parse_time("2026-12-01T23:30:00Z", "t")).hour == 17
    assert mx._us_central_offset(datetime(2026, 7, 1, tzinfo=timezone.utc)).total_seconds() == -5 * 3600
    assert mx._us_central_offset(datetime(2026, 12, 1, tzinfo=timezone.utc)).total_seconds() == -6 * 3600


def test_composio_failure_reported(nc, store, tmp_path, capsys):
    f = tmp_path / "fail.json"
    f.write_text(json.dumps({"successful": False, "error": "Invalid OAuth access token", "data": {}}))
    assert run(["ingest", "--store", str(store), "--reel", "r", "--pull", "48h", "--data", str(f)]) == 1
    assert "insights call failed: Invalid OAuth access token" in capsys.readouterr().err
    assert run(["account", "--store", str(store), "--data", str(f)]) == 1


def test_graph_error_body_reported(nc, store, tmp_path, capsys):
    f = tmp_path / "err.json"
    f.write_text(json.dumps({"data": {"error": {"message": "(#100) The value must be a valid insights metric",
                                                "type": "OAuthException", "code": 100}}}))
    assert run(["ingest", "--store", str(store), "--reel", "r", "--pull", "48h", "--data", str(f)]) == 1
    err = capsys.readouterr().err
    assert "ERROR: --data: the Instagram insights call failed: (#100) The value must be a valid insights metric (code 100)" in err
    f.write_text(json.dumps({"error": {"message": "Unsupported get request"}}))
    assert run(["account", "--store", str(store), "--data", str(f), "--date", "2026-01-01"]) == 1
    assert "Unsupported get request" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# post types (R337)
# ---------------------------------------------------------------------------
def test_post_type_tag_validation(nc, store, capsys):
    assert run(["tag", "--store", str(store), "--post", "c1", "--tags", json.dumps({"post_type": "Carousel"})]) == 0
    data = json.loads(store.read_text())
    assert data["reels"]["c1"]["tags"]["post_type"] == "carousel"
    assert run(["tag", "--store", str(store), "--post", "x", "--tags", json.dumps({"post_type": "video"})]) == 1
    assert "post_type must be one of reel, carousel, image, story, trial_reel" in capsys.readouterr().err
    # a Trial Reel is a reel: trial_reel true never goes with a carousel, here or merged with earlier tags
    assert run(["tag", "--store", str(store), "--post", "x", "--tags",
                json.dumps({"post_type": "image", "trial_reel": True})]) == 1
    assert run(["tag", "--store", str(store), "--post", "c1", "--tags", json.dumps({"trial_reel": True})]) == 1
    assert run(["tag", "--store", str(store), "--post", "t1", "--tags", json.dumps({"post_type": "trial_reel"})]) == 0
    data = json.loads(store.read_text())
    assert data["reels"]["t1"]["tags"]["trial_reel"] is True
    assert mx.post_type_of({"tags": {}}) == "reel" and mx.post_type_of({"tags": {"trial_reel": True}}) == "trial_reel"


def test_carousel_and_image_metrics(nc, store, tmp_path, capsys):
    """No watch time or skip rate for carousels and images: dropped with a WARN, computed as null, no error."""
    assert ingest(store, tmp_path, "c1", "48h", tags={"post_type": "carousel"}, views=900, reach=600, shares=12,
                  saved=30, ig_reels_avg_watch_time=5000, reels_skip_rate=10) == 0
    err = capsys.readouterr().err
    assert "avg_watch_time_ms does not apply to a carousel post" in err and "skip_rate" in err
    assert ingest(store, tmp_path, "i1", "7d", tags={"post_type": "image"}, views=400, reach=300, saved=3) == 0
    assert ingest(store, tmp_path, "r1", "48h", tags={"length": 30}, views=2000, reach=1500, shares=10,
                  ig_reels_avg_watch_time=12000, reels_skip_rate=40) == 0
    assert ingest(store, tmp_path, "r2", "48h", tags={"length": 20, "post_type": "trial_reel"}, views=500, reach=400,
                  ig_reels_avg_watch_time=6000, reels_skip_rate=60) == 0
    data = json.loads(store.read_text())
    c = data["reels"]["c1"]
    assert "avg_watch_time_ms" not in c["pulls"]["48h"]["metrics"] and "skip_rate" not in c["pulls"]["48h"]["metrics"]
    assert c["computed"]["post_type"] == "carousel"
    assert c["computed"]["retention"] is None and c["computed"]["avg_watch_time_s"] is None
    assert c["computed"]["skip_rate_vs_median"] is None and c["computed"]["sends_per_1k_reach"] == 20.0
    assert c["computed"]["saves_per_1k_reach"] == 50.0
    i = data["reels"]["i1"]["computed"]
    assert i["post_type"] == "image" and i["sends_per_1k_reach"] is None and i["retention"] is None
    # the skip-rate median is over reels and trial reels only
    assert data["reels"]["r1"]["computed"]["skip_rate_median"] == 50.0
    assert data["reels"]["r1"]["computed"]["skip_rate_vs_median"] == -10.0
    assert data["reels"]["r1"]["computed"]["retention"] == 0.4
    capsys.readouterr()
    assert run(["compute", "--store", str(store)]) == 0
    out = capsys.readouterr().out
    assert "c1 (carousel, 48h): sends_per_1k_reach=20, saves_per_1k_reach=50" in out
    assert run(["validate", "--store", str(store)]) == 0
    # a hand-edited store with a carousel's watch time fails validation
    data["reels"]["c1"]["pulls"]["48h"]["metrics"]["skip_rate"] = 12
    store.write_text(json.dumps(data))
    assert run(["validate", "--store", str(store)]) == 1
    assert "a carousel post has no skip_rate" in capsys.readouterr().err


def test_retagging_drops_video_metrics_and_stories_skip_due(nc, store, tmp_path, capsys):
    assert ingest(store, tmp_path, "p", "48h", views=10, reach=8, ig_reels_avg_watch_time=3000) == 0
    assert run(["tag", "--store", str(store), "--post", "p", "--tags", json.dumps({"post_type": "image"})]) == 0
    assert "avg_watch_time_ms does not apply to an image post" in capsys.readouterr().err
    data = json.loads(store.read_text())
    assert data["reels"]["p"]["pulls"]["48h"]["metrics"] == {"views": 10, "reach": 8}
    assert run(["tag", "--store", str(store), "--post", "s", "--tags",
                json.dumps({"post_type": "story", "posting_time": "2026-11-01T17:00:00-05:00"})]) == 0
    data = json.loads(store.read_text())
    assert mx.due(data, datetime(2026, 11, 12, tzinfo=timezone.utc)) == []
