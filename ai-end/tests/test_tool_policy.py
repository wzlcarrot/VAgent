"""参数级 Tool Policy 规则（借鉴 Codex execpolicy）。"""
from app.harness import tool_policy as tp
from app.harness.tool_policy import ToolPolicyRule, effective_decision


class TestEffectiveDecision:
    def _rule(self, **kw):
        base = dict(max_calls=5, timeout_seconds=10.0, decision="allow")
        base.update(kw)
        return ToolPolicyRule(**base)

    def test_no_rules_returns_base(self):
        rule = self._rule()
        assert effective_decision(rule, {"x": "1"}) == "allow"

    def test_exact_match_first_wins(self):
        rule = self._rule(arg_rules=(({"user_id": "root"}, "forbidden"),))
        assert effective_decision(rule, {"user_id": "root"}) == "forbidden"
        assert effective_decision(rule, {"user_id": "u1"}) == "allow"

    def test_prefix_match(self):
        rule = self._rule(arg_rules=(({"q": "secret*"}, "ask"),))
        assert effective_decision(rule, {"q": "secret123"}) == "ask"
        assert effective_decision(rule, {"q": "public"}) == "allow"

    def test_multi_condition_all_required(self):
        rule = self._rule(arg_rules=(({"a": "1", "b": "2"}, "forbidden"),))
        assert effective_decision(rule, {"a": "1", "b": "2"}) == "forbidden"
        assert effective_decision(rule, {"a": "1"}) == "allow"

    def test_missing_arg_no_match(self):
        rule = self._rule(arg_rules=(({"user_id": "root"}, "forbidden"),))
        assert effective_decision(rule, {}) == "allow"


class TestResolveRule:
    def test_parses_arg_rules(self, monkeypatch):
        monkeypatch.setattr(tp, "_POLICY_CACHE", {
            "global": {"default": {"decision": "allow"}},
            "workflows": {
                "wf": {"t": {"decision": "allow",
                             "rules": [{"match": {"x": "1"}, "decision": "forbidden"}]}},
            },
        })
        rule = tp.resolve_rule("wf", "t")
        assert rule.arg_rules == (({"x": "1"}, "forbidden"),)
        assert tp.effective_decision(rule, {"x": "1"}) == "forbidden"


class TestTypedPredicates:
    """类型化谓词：gte / lte / regex（借鉴 Codex execpolicy 的结构化匹配）。"""

    def _rule(self, **kw):
        base = dict(max_calls=5, timeout_seconds=10.0, decision="allow")
        base.update(kw)
        return ToolPolicyRule(**base)

    def test_gte_forbids_oversized_topk(self):
        rule = self._rule(arg_rules=(({"top_k": {"gte": 50}}, "forbidden"),))
        assert effective_decision(rule, {"top_k": 50}) == "forbidden"
        assert effective_decision(rule, {"top_k": 100}) == "forbidden"
        assert effective_decision(rule, {"top_k": 5}) == "allow"

    def test_gte_non_numeric_no_match(self):
        rule = self._rule(arg_rules=(({"top_k": {"gte": 50}}, "forbidden"),))
        assert effective_decision(rule, {"top_k": "many"}) == "allow"

    def test_lte(self):
        rule = self._rule(arg_rules=(({"top_k": {"lte": 0}}, "forbidden"),))
        assert effective_decision(rule, {"top_k": 0}) == "forbidden"
        assert effective_decision(rule, {"top_k": 3}) == "allow"

    def test_regex(self):
        rule = self._rule(arg_rules=(({"user_id": {"regex": "^admin"}}, "forbidden"),))
        assert effective_decision(rule, {"user_id": "admin_root"}) == "forbidden"
        assert effective_decision(rule, {"user_id": "u1"}) == "allow"

    def test_shipped_policy_blocks_huge_topk(self, monkeypatch):
        monkeypatch.setattr(tp, "_POLICY_CACHE", None)
        tp.load_policy(force=True)
        from app.agents.workflows.constants import WorkflowType
        rule = tp.resolve_rule(WorkflowType.VIDEO_QA, "search_video_chunks")
        assert tp.effective_decision(rule, {"top_k": 999}) == "forbidden"
        assert tp.effective_decision(rule, {"top_k": 5}) == "allow"
