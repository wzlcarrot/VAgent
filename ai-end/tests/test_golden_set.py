"""黄金集关键词路径回归：不调 LLM / embedding，锁住 easy 档下限。"""
import importlib.util
from pathlib import Path

from app.agents.router import Router

_GOLDEN_PATH = Path(__file__).resolve().parents[1] / "scripts" / "golden_set.py"
_spec = importlib.util.spec_from_file_location("golden_set", _GOLDEN_PATH)
_mod = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_mod)
GOLDEN_CASES = _mod.GOLDEN_CASES


class TestGoldenSetKeywordFloor:
    def test_case_count_and_intents(self):
        assert len(GOLDEN_CASES) >= 70
        expected = {c["expected"] for c in GOLDEN_CASES}
        assert len(expected) >= 4

    def test_easy_keyword_accuracy_floor(self):
        router = Router()
        easy = [c for c in GOLDEN_CASES if c.get("tier") == "easy"]
        assert len(easy) >= 40
        correct = 0
        for tc in easy:
            cands = router.route_candidates(tc["q"], tc.get("ctx") or {})
            top = cands[0][0] if cands else None
            if top == tc["expected"]:
                correct += 1
        acc = correct / len(easy)
        assert acc >= 0.80, f"easy 关键词准确率 {acc:.1%} < 80% ({correct}/{len(easy)})"
