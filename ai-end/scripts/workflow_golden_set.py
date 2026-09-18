#!/usr/bin/env python3
"""
全链路 Workflow Golden Set —— mock DB/LLM，验证各 workflow 输出形态。

用法:
  cd ai-end && python3 scripts/workflow_golden_set.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable, Dict
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.workflows.constants import WorkflowType  # noqa: E402
from app.tools.output_guard import VIDEO_QA_INSUFFICIENT_MSG  # noqa: E402


def _check_user_data_coin(result: Dict[str, Any]) -> bool:
    qr = result.get("query_result") or {}
    return qr.get("count") == 128 and "硬币" in (qr.get("summary_text") or "")


def _check_user_data_follow(result: Dict[str, Any]) -> bool:
    qr = result.get("query_result") or {}
    users = qr.get("users") or []
    return len(users) >= 1 and "科技小王" in (qr.get("summary_text") or "")


def _check_video_qa(result: Dict[str, Any]) -> bool:
    return bool(result.get("answer")) and bool(result.get("citations"))


def _check_video_qa_refuse(result: Dict[str, Any]) -> bool:
    return result.get("answer") == VIDEO_QA_INSUFFICIENT_MSG


def _check_chat(result: Dict[str, Any]) -> bool:
    return bool(result.get("answer"))


def _check_recommend(result: Dict[str, Any]) -> bool:
    vids = result.get("recommended_videos") or []
    return len(vids) >= 1 and bool(result.get("answer"))


CASES = [
    {
        "name": "user_data_coin",
        "workflow": WorkflowType.USER_DATA,
        "run": "user_data",
        "kwargs": {"question": "我的硬币有多少", "user_id": "u1"},
        "patches": [
            ("app.agents.workflows.user_data_workflow.UserTools.get_coin_count", lambda *_: 128),
            ("app.agents.workflows.user_data_workflow.LLM_tools.chat_sync", lambda *_a, **_k: "你当前共有 128 枚硬币。"),
        ],
        "check": _check_user_data_coin,
    },
    {
        "name": "user_data_follow",
        "workflow": WorkflowType.USER_DATA,
        "run": "user_data",
        "kwargs": {"question": "我关注的up主有哪些", "user_id": "u1"},
        "patches": [
            (
                "app.agents.workflows.user_data_workflow.UserTools.get_followings",
                lambda *_: {
                    "users": [{"user_id": "u2", "nick_name": "科技小王"}],
                    "total": 1,
                },
            ),
            ("app.agents.workflows.user_data_workflow.LLM_tools.chat_sync", lambda *_a, **_k: "你关注了科技小王。"),
        ],
        "check": _check_user_data_follow,
    },
    {
        "name": "video_qa_hit",
        "workflow": WorkflowType.VIDEO_QA,
        "run": "video_qa",
        "kwargs": {"question": "这个视频讲了什么", "video_id": "v1", "user_id": "u1"},
        "patches": [
            ("app.services.video_indexing.is_video_indexed", lambda *_: True),
            (
                "app.agents.workflows.video_qa_workflow.VideoTools.get_video_info",
                lambda *_: type("V", (), {
                    "videoId": "v1", "videoName": "Python教程", "nickName": "讲师",
                    "duration": 10, "tags": "编程", "introduction": "入门", "videoCover": "",
                })(),
            ),
            (
                "app.agents.workflows.video_qa_workflow.run_video_qa_react_retrieval",
                lambda **kw: (
                    [{"content": "Python 入门语法", "score": 0.9, "block_type": "intro", "video_id": "v1"}],
                    True,
                    1,
                    "",
                    "answered",
                ),
            ),
            (
                "app.agents.workflows.video_qa_workflow.LLM_tools.chat_sync",
                lambda *_a, **_k: "本视频讲解 Python 入门语法[1]。",
            ),
        ],
        "check": _check_video_qa,
    },
    {
        "name": "video_qa_refuse",
        "workflow": WorkflowType.VIDEO_QA,
        "run": "video_qa",
        "kwargs": {"question": "第三个实验参数是多少", "video_id": "v1", "user_id": "u1"},
        "patches": [
            ("app.services.video_indexing.is_video_indexed", lambda *_: True),
            (
                "app.agents.workflows.video_qa_workflow.VideoTools.get_video_info",
                lambda *_: type("V", (), {
                    "videoId": "v1", "videoName": "实验课", "nickName": "讲师",
                    "duration": 10, "tags": "实验", "introduction": "", "videoCover": "",
                })(),
            ),
            (
                "app.agents.workflows.video_qa_workflow.run_video_qa_react_retrieval",
                lambda **kw: ([], False, 1, "", "answered"),
            ),
        ],
        "check": _check_video_qa_refuse,
    },
    {
        "name": "chat_platform",
        "workflow": WorkflowType.CHAT,
        "run": "chat",
        "kwargs": {"question": "平台有什么功能"},
        "patches": [
            ("app.agents.workflows.chat_graph.RAGTools.retrieve_knowledge", lambda *_a, **_k: [{"content": "投稿、弹幕、AI助手"}]),
            ("app.agents.workflows.chat_graph.LLM_tools.chat_sync", lambda *_a, **_k: "ViewHub 支持投稿、弹幕与 AI 助手。"),
        ],
        "check": _check_chat,
    },
    {
        "name": "recommend_hit",
        "workflow": WorkflowType.RECOMMEND,
        "run": "recommend",
        "kwargs": {"question": "推荐一些科技视频", "user_id": "u1"},
        "patches": [
            (
                "app.tools.ranker.dual_recall_and_rerank",
                lambda *a, **k: [{"video_id": "v1", "score": 0.9, "content": "科技 AI 前沿"}],
            ),
            ("app.agents.workflows.recommend_workflow.UserTools.get_play_history", lambda *a, **k: []),
            ("app.agents.workflows.recommend_workflow.UserTools.get_favorites", lambda *a, **k: []),
            ("app.agents.workflows.recommend_workflow.UserTools.get_liked_videos", lambda *a, **k: ["v1"]),
            (
                "app.agents.workflows.recommend_workflow.VideoTools.get_video_info_batch",
                lambda ids: [
                    type("V", (), {
                        "videoId": "v1", "videoName": "科技前沿", "nickName": "科技小王",
                        "tags": "科技,AI", "videoCover": "", "duration": 10,
                        "categoryId": "1", "pCategoryId": None, "playCount": 100,
                        "createTime": "2025-01-01",
                    })()
                ],
            ),
            (
                "app.tools.memory_tools.MemoryTools.recall_memories",
                lambda *a, **k: [],
            ),
            (
                "app.tools.memory_tools.MemoryTools.get_negative_feedback_video_ids",
                lambda *a, **k: set(),
            ),
            (
                "app.agents.workflows.recommend_workflow.invoke_with_governor",
                lambda *a, **k: a[3]() if len(a) > 3 else [],
            ),
        ],
        "check": _check_recommend,
    },
]


def _run_case(case: Dict[str, Any]) -> tuple[str, bool, str]:
    runners: Dict[str, Callable] = {
        "user_data": lambda **kw: __import__(
            "app.agents.workflows.user_data_workflow", fromlist=["run_user_data_workflow"]
        ).run_user_data_workflow(**kw),
        "video_qa": lambda **kw: __import__(
            "app.agents.workflows.video_qa_workflow", fromlist=["run_video_qa_workflow"]
        ).run_video_qa_workflow(**kw),
        "chat": lambda **kw: __import__(
            "app.agents.workflows.chat_graph", fromlist=["run_chat_workflow"]
        ).run_chat_workflow(kw["question"], [], kw.get("session_id")),
        "recommend": lambda **kw: __import__(
            "app.agents.workflows.recommend_workflow", fromlist=["run_recommend_workflow"]
        ).run_recommend_workflow(kw["user_id"], kw.get("question"), kw.get("session_id"), kw.get("top_k", 5)),
    }
    fn = runners[case["run"]]
    patchers = [patch(target, side_effect=impl) if callable(impl) else patch(target, return_value=impl)
                for target, impl in case.get("patches", [])]
    try:
        for p in patchers:
            p.start()
        result = fn(**case["kwargs"])
        ok = case["check"](result)
        return ("PASS" if ok else "FAIL"), ok, str(result.get("answer", ""))[:80]
    except Exception as e:
        return "FAIL", False, str(e)[:80]
    finally:
        for p in reversed(patchers):
            p.stop()


def main():
    print("## Workflow Golden Set\n")
    print("| status | case | workflow | preview |")
    print("|--------|------|----------|---------|")
    passed = 0
    for case in CASES:
        status, ok, preview = _run_case(case)
        if ok:
            passed += 1
        print(f"| {status} | {case['name']} | {case['workflow']} | {preview} |")
    print(f"\n总计: {passed}/{len(CASES)}")
    sys.exit(0 if passed == len(CASES) else 1)


if __name__ == "__main__":
    main()
