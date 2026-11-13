"""chrome_queue.py: the queue of steps that need Claude in Chrome, with deadlines and fallbacks (R342)."""
from __future__ import annotations

import json
import subprocess
import sys

import pytest

import chrome_queue
import numa_common


def run(argv):
    with pytest.raises(SystemExit) as e:
        numa_common.run_cli(chrome_queue.main, argv)
    return e.value.code


@pytest.fixture
def q(tmp_path, nc, monkeypatch, capsys):
    monkeypatch.delenv("NUMA_STATE", raising=False)
    state = tmp_path / "_Plan"

    def call(*argv, code=0):
        capsys.readouterr()
        assert run([*argv, "--state", str(state)]) == code
        out = capsys.readouterr()
        return json.loads(out.out) if "--json" in argv and code == 0 else out

    call.state = state
    return call


def add(q, kind="trial_reel", payload=None, deadline="2026-12-10T17:00:00-06:00",
        fallback="Post as a normal reel and note it", now="2026-12-10T05:20:00-06:00"):
    payload = payload or {"job": "Day 10 - 2026-12-10 - Cold snap calm"}
    return q("add", "--kind", kind, "--payload", json.dumps(payload), "--deadline", deadline, "--fallback", fallback,
             "--now", now, "--json")


def test_add_list_next_done(q):
    a = add(q)
    assert a["added"] and a["item"]["id"].startswith("trial_reel-") and a["item"]["status"] == "pending"
    assert a["item"]["deadline"] == "2026-12-10T17:00:00-06:00" and a["item"]["attempts"] == 0
    b = add(q, kind="competitor_log", payload={"month": "2026-12"}, deadline="2026-12-31T23:59:00",
            fallback="Keep the web-search competitor log")
    assert b["item"]["deadline"] == "2026-12-31T23:59:00-06:00"  # naive = Central
    listed = q("list", "--json")["items"]
    assert [i["kind"] for i in listed] == ["trial_reel", "competitor_log"]
    nxt = q("next", "--now", "2026-12-10T09:00:00-06:00", "--json")
    assert nxt["item"]["id"] == a["item"]["id"] and nxt["pending"] == 2
    done = q("done", a["item"]["id"], "--result", "posted as Trial Reel: https://www.instagram.com/reel/x",
             "--now", "2026-12-10T16:40:00-06:00", "--json")
    assert done["item"]["status"] == "done" and done["item"]["done_at"] == "2026-12-10T22:40:00Z"
    assert q("next", "--now", "2026-12-10T17:30:00-06:00", "--json")["item"]["kind"] == "competitor_log"
    assert [i["status"] for i in q("list", "--status", "all", "--json")["items"]] == ["pending", "done"]


def test_dedupe_identical_items(q):
    a = add(q, payload={"job": "J", "partner": "Mission Fitness"})
    b = add(q, payload={"partner": "Mission Fitness", "job": "J"}, deadline="2026-12-10T16:00:00-06:00")
    assert not b["added"] and b["item"]["id"] == a["item"]["id"]
    assert b["item"]["deadline"] == "2026-12-10T16:00:00-06:00"  # the earlier deadline wins
    c = add(q, payload={"job": "J", "partner": "Mission Fitness"}, deadline="2026-12-11T16:00:00-06:00")
    assert not c["added"] and c["item"]["deadline"] == "2026-12-10T16:00:00-06:00"
    assert len(q("list", "--json")["items"]) == 1
    assert add(q, kind="collab_invite", payload={"job": "J", "partner": "Mission Fitness"})["added"]  # other kind
    q("done", a["item"]["id"], "--result", "posted")
    assert not add(q, payload={"job": "J", "partner": "Mission Fitness"})["added"]  # already done: not redone
    text = q("add", "--kind", "trial_reel", "--payload", '{"job": "J", "partner": "Mission Fitness"}',
             "--deadline", "2026-12-10T17:00", "--fallback", "x").out
    assert "already queued, done" in text


def test_expire_returns_fallbacks_and_requeue_after_expiry(q):
    a = add(q, kind="ai_label", payload={"job": "J"}, fallback="Do not post; Jude gets section 6's line")
    add(q, kind="competitor_log", payload={"month": "2026-12"}, deadline="2026-12-31T23:59:00-06:00",
        fallback="Keep the web-search log")
    assert q("expire", "--now", "2026-12-10T16:59:00-06:00", "--json")["expired"] == []
    ex = q("expire", "--now", "2026-12-10T17:00:00-06:00", "--json")["expired"]
    assert [(i["id"], i["fallback"]) for i in ex] == [(a["item"]["id"], "Do not post; Jude gets section 6's line")]
    assert ex[0]["status"] == "expired" and ex[0]["expired_at"] == "2026-12-10T23:00:00Z"
    assert q("expire", "--now", "2026-12-11T00:00:00-06:00", "--json")["expired"] == []  # only once
    assert q("next", "--now", "2026-12-11T00:00:00-06:00", "--json")["item"]["kind"] == "competitor_log"
    q("done", a["item"]["id"], "--result", "late", code=1)
    again = add(q, kind="ai_label", payload={"job": "J"}, deadline="2026-12-12T17:00:00-06:00")
    assert again["added"] and again["item"]["id"] == a["item"]["id"] + "-2"
    text = q("expire", "--now", "2026-12-13T00:00:00-06:00").out
    assert f"EXPIRED: {again['item']['id']}" in text and "fallback:" in text


def test_next_skips_past_deadlines_and_none_left(q):
    add(q, deadline="2026-12-10T08:00:00-06:00")
    assert q("next", "--now", "2026-12-10T09:00:00-06:00", "--json") == {"item": None, "pending": 0}
    assert q("next", "--now", "2026-12-10T09:00:00-06:00").out.strip() == "none"


def test_fail_keeps_item_pending(q):
    a = add(q, kind="scout_research", payload={"for": "plan-month 2026-12", "what": "offers on Instagram"},
            deadline="2026-12-01T00:00:00-06:00", fallback="Plan stands on web-search facts")
    f = q("fail", a["item"]["id"], "--reason", "Instagram asked to log in again", "--now", "2026-11-25T10:00:00",
          "--json")
    assert f["item"]["status"] == "pending" and f["item"]["attempts"] == 1
    assert f["item"]["last_error"].endswith("Instagram asked to log in again")
    assert q("next", "--now", "2026-11-25T11:00:00", "--json")["item"]["id"] == a["item"]["id"]


@pytest.mark.parametrize("argv,code,msg", [
    (["add", "--kind", "tiktok", "--payload", "{}", "--deadline", "2026-12-10", "--fallback", "x"], 2, "invalid choice"),
    (["add", "--kind", "ai_label", "--payload", "[1]", "--deadline", "2026-12-10", "--fallback", "x"], 1, "JSON object"),
    (["add", "--kind", "ai_label", "--payload", "{bad", "--deadline", "2026-12-10", "--fallback", "x"], 1, "valid JSON"),
    (["add", "--kind", "ai_label", "--payload", '{"a":1}', "--deadline", "soon", "--fallback", "x"], 1, "ISO 8601"),
    (["add", "--kind", "ai_label", "--payload", '{"a":1}', "--deadline", "2026-12-10", "--fallback", " "], 1, "--fallback"),
    (["done", "nope", "--result", "x"], 1, "no item nope"),
    (["done", "nope"], 2, "--result"),
])
def test_input_errors(q, argv, code, msg):
    out = q(*argv, code=code)
    assert msg in out.err and "Traceback" not in out.err


def test_every_kind_is_accepted(q):
    for i, kind in enumerate(chrome_queue.KINDS):
        assert add(q, kind=kind, payload={"n": i})["added"]
    assert set(chrome_queue.KINDS) == {"scout_research", "competitor_log", "trial_reel", "collab_invite", "ai_label",
                                       "higgsfield_unlimited"}


def test_merge_with_drive_copy(q, tmp_path):
    a = add(q, payload={"job": "A"})
    b = add(q, payload={"job": "B"})
    drive = json.loads((q.state / "chrome_queue.json").read_text())
    drive["items"][0].update(status="done", result="posted", done_at="2026-12-10T22:00:00Z")
    drive["items"][1]["attempts"] = 2
    drive["items"].append({**drive["items"][1], "id": "collab_invite-x", "kind": "collab_invite",
                           "payload": {"job": "C"}, "attempts": 0})
    f = tmp_path / "drive_queue.json"
    f.write_text(json.dumps(drive))
    out = q("merge", str(f), "--json")
    assert out["added"] == 1 and out["items"] == 3
    items = {i["id"]: i for i in q("list", "--status", "all", "--json")["items"]}
    assert items[a["item"]["id"]]["status"] == "done"  # done wins over pending
    assert items[b["item"]["id"]]["attempts"] == 2
    q("merge", str(tmp_path / "none.json"), code=1)


def test_bad_queue_file(q):
    q.state.mkdir(parents=True)
    (q.state / "chrome_queue.json").write_text('{"items": [{"id": "x"}]}')
    assert "every item needs" in q("list", code=1).err


def test_concurrent_adds(tmp_path, scripts_dir, nc):
    state = tmp_path / "s"
    procs = [subprocess.Popen([sys.executable, str(scripts_dir / "chrome_queue.py"), "add", "--kind", "scout_research",
                               "--payload", json.dumps({"n": i}), "--deadline", "2026-12-10T05:00:00",
                               "--fallback", "web search stands", "--state", str(state)],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for i in range(6)]
    for p in procs:
        p.communicate(timeout=60)
        assert p.returncode == 0
    assert len(json.loads((state / "chrome_queue.json").read_text())["items"]) == 6
