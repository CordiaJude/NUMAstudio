import sys
sys.path.insert(0, "/home/user/NUMAstudio/tests/unit")
from test_baseline_plan import *  # noqa
def test_dbg(make_job):
    for shape in ("photos", "music_only"):
        work, A = make_job(shape)
        for dur in (None, 15.0, 16.0, 17.0, 20.0):
            plan = build(work, A, duration=dur, script="Three minutes of cold.\nWalk out wide awake.\nRelax, breathe, disconnect.")
            ec = plan["endcard"]["t"]
            print(shape, dur, plan["duration"], ec, [_beats(s) for s in plan["shots"]], [(l["words"][0][1], l["end"]) for l in plan["lines"]])
