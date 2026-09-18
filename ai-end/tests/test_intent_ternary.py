"""意图三分路由回归（qa / recommend / chitchat）。"""
from app.harness.intent_ternary import run_ternary


def test_intent_ternary_floor():
    report = run_ternary()
    assert report["accuracy"] >= 0.85, report["failures"]
    for bucket in ("qa", "recommend", "chitchat"):
        st = report["buckets"][bucket]
        assert st["passed"] / st["total"] >= 0.8, (bucket, st, report["failures"])
