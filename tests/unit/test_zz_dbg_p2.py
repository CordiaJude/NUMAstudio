from test_engine import *  # noqa
from test_engine import short_plan
def test_dbg(plan_factory, ramp_image):
    p = short_plan(plan_factory, size=[540, 960], leaks=[],
                   lines=[{"words": [["Walk", 0.1], ["out", 0.3], ["wide", 0.5], ["awake.", 0.7, 1]], "end": 1.8}],
                   shots=[{"src": str(ramp_image), "look": "none", "t0": 0.0, "t1": 2.0, "z": [1.0, 1.25],
                           "pan": [0.1, 0.05], "tr": "cut"}])
    p.pop("endcard")
    with engine.Renderer(p) as r:
        r.frame(1.0)
        print("SCRIMS", {k: (None if v is None else (v[0], round(v[3], 3))) for k, v in r._scrims.items()}, r.caption_boxes)
