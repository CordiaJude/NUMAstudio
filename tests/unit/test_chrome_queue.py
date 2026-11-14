"""chrome_queue.py: the queue of steps that need Claude in Chrome, with claims, deadlines and fallbacks (R342)."""
from __future__ import annotations

import json
import subprocess
import sys

import pytest

import chrome_queue
import numa_common

RUN_A = "chrome_queue-20261210T224700Z-aaaa"
RUN_B = "chrome_queue-20261210T224700Z-bbbb"
NIGHT = "night_check-20261211T020000Z-cccc"


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
        fallback="Stays staged; the approver is told", now="2026-12-10T05:20:00-06:00", *extra):
    payload = payload or {"job": "Day 10 - 2026-12-10 - Cold snap calm"}
    return q("add", "--kind", kind, "--payload", json.dumps(payload), "--deadline", deadline, "--fallback", fallback,
             "--now", now, "--json", *extra)


def claim(q, run_id=RUN_A, now="2026-12-10T09:00:00-06:00", *extra):
    return q("next", "--claim", run_id, "--now", now, "--json", *extra)


def test_add_list_claim_done(q):
    a = add(q)
    assert a["added"] and a["item"]["id"].startswith("trial_reel-") and a["item"]["status"] == "pending"
    b = add(q, "competitor_log", {"month": "2026-12"}, "2026-12-31T23:59:00", "Keep the web-search competitor log")
    assert b["item"]["deadline"] == "2026-12-31T23:59:00-06:00"  # naive = Central
    assert [i["kind"] for i in q("list", "--json")["items"]] == ["trial_reel", "competitor_log"]
    peek = q("next", "--now", "2026-12-10T09:00:00-06:00", "--json")
    assert peek["item"]["id"] == a["item"]["id"] and not peek["claimed"]
    assert q("list", "--json")["items"][0]["status"] == "pending"  # a peek changes nothing
    c = claim(q)
    assert c["claimed"] and c["item"]["status"] == "in_progress" and c["item"]["claimed_by"] == RUN_A
    assert c["item"]["lease_until"] == "2026-12-10T15:45:00Z"  # 45 min lease
    assert claim(q, RUN_B)["item"]["kind"] == "competitor_log"  # the claimed one is not handed out again
    q("done", a["item"]["id"], "--claim", RUN_B, "--result", "x", code=1)  # not B's claim
    done = q("done", a["item"]["id"], "--claim", RUN_A, "--result", "posted as Trial Reel: permalink",
             "--now", "2026-12-10T09:20:00-06:00", "--json")
    assert done["item"]["status"] == "done" and done["item"]["done_at"] == "2026-12-10T15:20:00Z"


def test_two_parallel_drainers_get_one_claim(tmp_path, scripts_dir, nc):
    """B1: two drainers ask at the same moment; exactly one gets the item."""
    state = tmp_path / "s"
    subprocess.run([sys.executable, str(scripts_dir / "chrome_queue.py"), "add", "--kind", "ai_label", "--payload",
                    '{"job": "J"}', "--deadline", "2099-01-01T00:00:00", "--fallback", "stays staged",
                    "--state", str(state)], check=True, capture_output=True)
    for _ in range(3):
        procs = [subprocess.Popen([sys.executable, str(scripts_dir / "chrome_queue.py"), "next", "--claim", rid,
                                   "--json", "--state", str(state)], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  text=True) for rid in (RUN_A, RUN_B)]
        outs = [json.loads(p.communicate(timeout=60)[0]) for p in procs]
        assert sorted(o["claimed"] for o in outs) == [False, True]
        data = json.loads((state / "chrome_queue.json").read_text())
        winner = next(o for o in outs if o["claimed"])["item"]["claimed_by"]
        assert data["items"][0]["claimed_by"] == winner
        subprocess.run([sys.executable, str(scripts_dir / "chrome_queue.py"), "fail", data["items"][0]["id"],
                        "--claim", winner, "--reason", "retry", "--state", str(state)], check=True,
                       capture_output=True)


def test_lease_runs_out_and_item_returns(q):
    a = add(q)
    claim(q, RUN_A, "2026-12-10T09:00:00-06:00", "--lease-minutes", "10")
    assert claim(q, RUN_B, "2026-12-10T09:05:00-06:00")["item"] is None
    again = claim(q, RUN_B, "2026-12-10T09:11:00-06:00")
    assert again["item"]["id"] == a["item"]["id"] and again["item"]["claimed_by"] == RUN_B
    assert again["item"]["attempts"] == 1 and "lease of " + RUN_A in again["item"]["last_error"]
    q("done", a["item"]["id"], "--claim", RUN_A, "--result", "late", code=1)  # A lost its claim


def test_fail_returns_item_to_pending(q):
    a = add(q, "scout_research", {"for": "plan-month 2026-12", "what": "offers on Instagram"},
            "2026-12-01T00:00:00-06:00", "Plan stands on web-search facts", "2026-11-25T09:00:00-06:00")
    claim(q, RUN_A, "2026-11-25T10:00:00")
    f = q("fail", a["item"]["id"], "--claim", RUN_A, "--reason", "Instagram asked to log in again",
          "--now", "2026-11-25T10:05:00", "--json")
    assert f["item"]["status"] == "pending" and f["item"]["attempts"] == 1 and f["item"]["claimed_by"] is None
    assert f["item"]["last_error"].endswith("Instagram asked to log in again")
    assert claim(q, RUN_B, "2026-11-25T11:00:00")["item"]["id"] == a["item"]["id"]


def test_dedupe_identical_items(q):
    a = add(q, payload={"job": "J", "partner": "Mission Fitness"})
    b = add(q, payload={"partner": "Mission Fitness", "job": "J"}, deadline="2026-12-10T16:00:00-06:00")
    assert not b["added"] and b["item"]["id"] == a["item"]["id"]
    assert b["item"]["deadline"] == "2026-12-10T16:00:00-06:00"  # the earlier deadline wins
    c = add(q, payload={"job": "J", "partner": "Mission Fitness"}, deadline="2026-12-11T16:00:00-06:00")
    assert not c["added"] and c["item"]["deadline"] == "2026-12-10T16:00:00-06:00"
    assert len(q("list", "--json")["items"]) == 1
    assert add(q, kind="collab_invite", payload={"job": "J", "partner": "Mission Fitness"})["added"]  # other kind
    claim(q)
    q("done", a["item"]["id"], "--claim", RUN_A, "--result", "posted")
    assert not add(q, payload={"job": "J", "partner": "Mission Fitness"})["added"]  # already done: not redone


def test_dedupe_never_puts_not_before_after_the_deadline(q):
    """Minor 3: an earlier deadline from a duplicate that would come before not_before is refused."""
    add(q, payload={"job": "K"}, deadline="2026-12-10T17:00:00-06:00", now="2026-12-10T05:00:00-06:00")
    q("add", "--kind", "ai_label", "--payload", '{"job": "L"}', "--not-before", "2026-12-10T15:45",
      "--deadline", "2026-12-10T17:00", "--fallback", "stays staged")
    out = q("add", "--kind", "ai_label", "--payload", '{"job": "L"}', "--deadline", "2026-12-10T15:00",
            "--fallback", "stays staged", code=1)
    assert "would come before it" in out.err
    item = next(i for i in q("list", "--json")["items"] if i["kind"] == "ai_label")
    assert item["deadline"] == "2026-12-10T17:00:00-06:00"


def test_not_before_holds_an_item_back(q):
    a = q("add", "--kind", "trial_reel", "--payload", '{"job": "J"}', "--not-before", "2026-12-10T15:45:00",
          "--deadline", "2026-12-10T17:00:00", "--fallback", "Stays staged", "--json")
    assert a["item"]["not_before"] == "2026-12-10T15:45:00-06:00"
    peek = q("next", "--now", "2026-12-10T09:47:00-06:00", "--json")
    assert peek["item"] is None and peek["waiting"] == 1
    assert claim(q, RUN_A, "2026-12-10T15:47:00-06:00")["item"]["id"] == a["item"]["id"]  # the :47 run in T-75 min
    q("add", "--kind", "ai_label", "--payload", '{"job": "J"}', "--not-before", "2026-12-10T17:00",
      "--deadline", "2026-12-10T17:00", "--fallback", "x", code=1)


def test_kinds_filter(q):
    add(q, "ai_label", {"job": "J"})
    add(q, "competitor_log", {"month": "2026-12"}, "2026-12-31T23:59:00")
    got = claim(q, RUN_A, "2026-12-10T09:00:00", "--kinds", "scout_research,competitor_log,higgsfield_unlimited")
    assert got["item"]["kind"] == "competitor_log"
    q("next", "--kinds", "tiktok", code=2)


def test_expire_with_margin_by_the_designated_runner(q):
    a = add(q, "ai_label", {"job": "J"}, fallback="Stays staged; the approver is told")
    add(q, "competitor_log", {"month": "2026-12"}, "2026-12-31T23:59:00-06:00", "Keep the web-search log")
    q("expire", "--now", "2026-12-10T17:30:00-06:00", code=2)  # --run is required
    assert q("expire", "--run", NIGHT, "--now", "2026-12-10T17:30:00-06:00", "--json")["expired"] == []  # margin
    ex = q("expire", "--run", NIGHT, "--now", "2026-12-10T18:00:00-06:00", "--json")["expired"]
    assert [(i["id"], i["fallback"], i["expired_by"]) for i in ex] == [
        (a["item"]["id"], "Stays staged; the approver is told", NIGHT)]
    assert q("expire", "--run", NIGHT, "--now", "2026-12-11T00:00:00-06:00", "--json")["expired"] == []  # once
    again = add(q, "ai_label", {"job": "J"}, "2026-12-12T17:00:00-06:00")
    assert again["added"] and again["item"]["id"] == a["item"]["id"] + "-2"
    assert "EXPIRED:" in q("expire", "--run", NIGHT, "--now", "2026-12-13T00:00:00-06:00", "--margin-minutes", "0").out


def test_a_live_claim_is_not_expired_but_a_lapsed_one_is(q):
    a = add(q, "trial_reel", {"job": "J"}, "2026-12-10T17:00:00-06:00")
    claim(q, RUN_A, "2026-12-10T16:50:00-06:00", "--lease-minutes", "90")
    assert q("expire", "--run", NIGHT, "--now", "2026-12-10T18:05:00-06:00", "--json")["expired"] == []
    ex = q("expire", "--run", NIGHT, "--now", "2026-12-10T18:30:00-06:00", "--json")["expired"]
    assert [i["id"] for i in ex] == [a["item"]["id"]]


def test_done_after_expiry_is_a_reported_conflict(q):
    a = add(q, "ai_label", {"job": "J"}, "2026-12-10T17:00:00-06:00")
    claim(q, RUN_A, "2026-12-10T16:50:00-06:00", "--lease-minutes", "15")
    q("expire", "--run", NIGHT, "--now", "2026-12-10T20:00:00-06:00")
    out = q("done", a["item"]["id"], "--claim", RUN_A, "--result", "posted with AI label", code=1)
    assert "conflict" in out.err
    item = q("list", "--status", "conflict", "--json")["items"][0]
    assert item["conflict"]["done_by"] == RUN_A and item["conflict"]["expired_by"] == NIGHT
    assert q("expire", "--run", NIGHT, "--now", "2026-12-11T20:00:00-06:00", "--json")["conflicts"][0]["id"] == a["item"]["id"]


@pytest.mark.parametrize("argv,code,msg", [
    (["add", "--kind", "tiktok", "--payload", "{}", "--deadline", "2026-12-10", "--fallback", "x"], 2, "invalid choice"),
    (["add", "--kind", "ai_label", "--payload", "[1]", "--deadline", "2026-12-10", "--fallback", "x"], 1, "JSON object"),
    (["add", "--kind", "ai_label", "--payload", "{bad", "--deadline", "2026-12-10", "--fallback", "x"], 1, "valid JSON"),
    (["add", "--kind", "ai_label", "--payload", '{"a":1}', "--deadline", "soon", "--fallback", "x"], 1, "ISO 8601"),
    (["add", "--kind", "ai_label", "--payload", '{"a":1}', "--deadline", "2026-12-10", "--fallback", " "], 1, "--fallback"),
    (["done", "nope", "--claim", RUN_A, "--result", "x"], 1, "no item nope"),
    (["done", "nope", "--result", "x"], 2, "--claim"),
])
def test_input_errors(q, argv, code, msg):
    out = q(*argv, code=code)
    assert msg in out.err and "Traceback" not in out.err


def test_every_kind_is_accepted(q):
    for i, kind in enumerate(chrome_queue.KINDS):
        assert add(q, kind, {"n": i})["added"]
    assert set(chrome_queue.KINDS) == {"scout_research", "competitor_log", "trial_reel", "collab_invite", "ai_label",
                                       "higgsfield_unlimited"}
    assert set(chrome_queue.POSTING_KINDS) == {"trial_reel", "collab_invite", "ai_label"}


def _upload(files, drive):
    for f in files:
        (drive / f.rsplit("/", 1)[-1]).write_text(open(f).read())


def test_per_item_files_and_merge_dir(q, tmp_path):
    """N3: each item is its own Drive file; two runs adding at the same moment never drop each other's item."""
    drive = tmp_path / "drive_queue"
    drive.mkdir()
    a = add(q, payload={"job": "A"})
    assert a["files"] == [str(q.state / "chrome_queue" / f"{a['item']['id']}.json")]
    _upload(a["files"], drive)
    other = tmp_path / "other"                                  # a second machine, same Drive starting point
    assert run(["merge-dir", str(drive), "--state", str(other)]) == 0
    capsys_add = run(["add", "--kind", "ai_label", "--payload", '{"job": "B"}', "--deadline", "2026-12-10T17:00",
                      "--fallback", "stays staged", "--state", str(other)])
    assert capsys_add == 0
    _upload([str(f) for f in (other / "chrome_queue").glob("ai_label-*.json")], drive)
    c = add(q, payload={"job": "C"})                            # this machine uploads only its own new item
    assert c["files"] == [str(q.state / "chrome_queue" / f"{c['item']['id']}.json")]
    _upload(c["files"], drive)
    out = q("merge-dir", str(drive), "--json")
    assert out["items"] == 3 and out["added"] == 1
    assert {i["payload"]["job"] for i in q("list", "--json")["items"]} == {"A", "B", "C"}
    claimed = claim(q)
    assert claimed["files"] == [str(q.state / "chrome_queue" / f"{claimed['item']['id']}.json")]
    (drive / "junk.json").write_text("{bad")
    assert q("merge-dir", str(drive), "--json")["skipped"] == 1
    q("merge-dir", str(tmp_path / "missing"), code=1)          # a failed download is never "absent"


def test_merge_rules_with_drive_copy(q, tmp_path):
    a = add(q, payload={"job": "A"})
    b = add(q, payload={"job": "B"})
    c = add(q, payload={"job": "C"})
    local = json.loads((q.state / "chrome_queue.json").read_text())
    drive = tmp_path / "drive_queue"
    drive.mkdir()
    items = {i["id"]: dict(i) for i in local["items"]}
    items[a["item"]["id"]].update(status="in_progress", claimed_by=RUN_A, claimed_at="2026-12-10T15:00:00Z")
    items[b["item"]["id"]].update(status="done", result="posted", done_at="2026-12-10T22:00:00Z", claimed_by=RUN_A)
    items[c["item"]["id"]].update(attempts=2)
    for i in items.values():
        (drive / f"{i['id']}.json").write_text(json.dumps(i))
    (drive / "collab_invite-x.json").write_text(json.dumps({**items[c["item"]["id"]], "id": "collab_invite-x",
                                                            "kind": "collab_invite", "payload": {"job": "D"},
                                                            "attempts": 0}))
    for i in local["items"]:                                   # local: a later claim of A, B and C expired
        if i["id"] == a["item"]["id"]:
            i.update(status="in_progress", claimed_by=RUN_B, claimed_at="2026-12-10T15:05:00Z")
        else:
            i.update(status="expired", expired_at="2026-12-11T02:00:00Z", expired_by=NIGHT)
    (q.state / "chrome_queue.json").write_text(json.dumps(local))
    out = q("merge-dir", str(drive), "--json")
    assert out["added"] == 1 and out["items"] == 4 and out["conflicts"] == 1
    got = {i["id"]: i for i in q("list", "--status", "all", "--json")["items"]}
    assert got[a["item"]["id"]]["claimed_by"] == RUN_A                 # the earlier claim wins
    assert got[b["item"]["id"]]["status"] == "conflict"                # done there, expired here
    assert got[c["item"]["id"]]["status"] == "expired" and got[c["item"]["id"]]["attempts"] == 2


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
