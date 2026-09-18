"""工具结果投影：头/尾截断 + 溢出提示（借鉴 pi/Claude Code）。"""
from app.harness.tool_projection import attach_spill_notice, project_tool_result


class TestStringTruncation:
    def test_head_default_keeps_start(self):
        text = "START" + "x" * 200 + "END"
        out = project_tool_result(text, max_chars=30)
        assert out.startswith("START")
        assert "truncated" in out

    def test_tail_keeps_end_and_error(self):
        text = "x" * 200 + "\n❌ ERROR: 数据库超时"
        out = project_tool_result(text, max_chars=60, keep="tail")
        assert "ERROR" in out  # 末尾的报错保住了
        assert "truncated" in out

    def test_short_string_unchanged(self):
        assert project_tool_result("hi", max_chars=100) == "hi"


class TestListTruncation:
    def test_head_keeps_first_with_marker(self):
        items = [{"content": "a" * 100} for _ in range(10)]
        out = project_tool_result(items, max_chars=120)
        assert out is not items
        assert out[-1].get("truncated") is True
        assert out[-1].get("remaining", 0) > 0

    def test_tail_keeps_last_with_marker(self):
        items = [{"content": f"item-{i}"} for i in range(10)]
        out = project_tool_result(items, max_chars=60, keep="tail")
        assert out[0].get("truncated") is True
        # 末尾的 item-9 应保留
        assert any("item-9" in str(x) for x in out)

    def test_no_truncation_returns_same_object(self):
        items = [{"content": "short"}]
        assert project_tool_result(items, max_chars=10000) is items


class TestDictTruncation:
    def test_no_truncation_returns_same_object(self):
        doc = {"content": "short"}
        assert project_tool_result(doc, max_chars=10000) is doc

    def test_truncation_sets_flag(self):
        doc = {"content": "x" * 100, "id": 1}
        out = project_tool_result(doc, max_chars=30)
        assert out is not doc
        assert out["_truncated"] is True
        assert out["id"] == 1  # 结构化字段保留


class TestSpillNotice:
    def test_str(self):
        out = attach_spill_notice("abc", "/tmp/full.txt")
        assert out.startswith("abc")
        assert "已存" in out and "/tmp/full.txt" in out

    def test_list(self):
        out = attach_spill_notice([{"a": 1}], "/tmp/full.txt")
        assert out[-1] == {"_full_output": "/tmp/full.txt"}

    def test_dict(self):
        out = attach_spill_notice({"a": 1}, "/tmp/full.txt")
        assert out["_full_output"] == "/tmp/full.txt"
        assert out["a"] == 1

    def test_empty_path_noop(self):
        original = [1, 2]
        assert attach_spill_notice(original, "") is original
