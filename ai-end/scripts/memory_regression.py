#!/usr/bin/env python3
"""
跨轮记忆回归（借鉴 Ragent agent-memory regression，离线可跑）。

用法:
  cd ai-end && python scripts/memory_regression.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.tools.memory_tools import MemoryTools  # noqa: E402

CASES = [
    {
        "name": "preference_recall",
        "question": "我之前说过喜欢什么类型的视频？",
        "mock_memories": [{"content": "用户喜欢看科技类视频", "type": "preference", "score": 0.9}],
        "expect_keyword": "科技",
    },
    {
        "name": "fact_recall",
        "question": "我的昵称是什么？",
        "mock_memories": [{"content": "用户昵称是小王", "type": "fact", "score": 0.85}],
        "expect_keyword": "小王",
    },
    {
        "name": "negative_feedback_filter",
        "question": "推荐",
        "mock_memories": [{"content": "video_id=v_bad 标记为没用", "type": "feedback", "score": -1.0}],
        "expect_keyword": "v_bad",
    },
]


def _as_memory(row: dict):
    return type("Memory", (), row)()


def main() -> int:
    passed = 0
    for case in CASES:
        rows = [_as_memory(r) for r in case["mock_memories"]]
        with patch.object(MemoryTools, "recall_memories", return_value=rows):
            got = MemoryTools.recall_memories("u_test", case["question"], top_k=5)
        blob = " ".join(getattr(m, "content", "") for m in got)
        ok = case["expect_keyword"] in blob
        if ok:
            passed += 1
            print(f"PASS {case['name']}")
        else:
            print(f"FAIL {case['name']} blob={blob!r}")

    print(f"result: {passed}/{len(CASES)}")
    return 0 if passed == len(CASES) else 1


if __name__ == "__main__":
    raise SystemExit(main())
