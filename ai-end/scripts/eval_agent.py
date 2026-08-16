"""
Agent 评测脚本
评估 Router 路由准确率 + Workflow 回答质量
用法: python scripts/eval_agent.py
"""

import logging
import sys

sys.path.insert(0, ".")

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

from app.agents.workflows.constants import WorkflowType  # noqa: E402

TEST_CASES = [
    # (question, video_id, user_id, expected_workflow)
    {"question": "这个视频讲了什么", "video_id": "test001", "user_id": None, "expected": WorkflowType.VIDEO_QA},
    {"question": "视频的重点是什么", "video_id": "test001", "user_id": None, "expected": WorkflowType.VIDEO_QA},
    {"question": "帮我总结这个视频", "video_id": "test001", "user_id": None, "expected": WorkflowType.VIDEO_QA},
    {"question": "推荐一些好看的视频", "video_id": None, "user_id": "u001", "expected": WorkflowType.RECOMMEND},
    {"question": "有什么好看的", "video_id": None, "user_id": "u001", "expected": WorkflowType.RECOMMEND},
    {"question": "热门视频有哪些", "video_id": None, "user_id": None, "expected": WorkflowType.RECOMMEND},
    {"question": "我今天的点赞数", "video_id": None, "user_id": "u001", "expected": WorkflowType.USER_DATA},
    {"question": "我的收藏记录", "video_id": None, "user_id": "u001", "expected": WorkflowType.USER_DATA},
    {"question": "我的播放历史", "video_id": None, "user_id": "u001", "expected": WorkflowType.USER_DATA},
    {"question": "你们平台有什么功能", "video_id": None, "user_id": None, "expected": WorkflowType.CHAT},
    {"question": "你好", "video_id": None, "user_id": None, "expected": WorkflowType.CHAT},
    {"question": "怎么上传视频", "video_id": None, "user_id": None, "expected": WorkflowType.CHAT},
    {"question": "这个视频怎么样", "video_id": None, "user_id": None, "expected": WorkflowType.CHAT},
    {"question": "今天天气怎么样", "video_id": None, "user_id": None, "expected": WorkflowType.CHAT},
]


def eval_router():
    from app.agents.router import Router
    router = Router()

    total = len(TEST_CASES)
    correct = 0
    results = []

    for tc in TEST_CASES:
        context = {}
        if tc["video_id"]:
            context["video_id"] = tc["video_id"]
        predicted = router.hybrid_route(tc["question"], context)
        is_correct = predicted == tc["expected"]
        if is_correct:
            correct += 1
        results.append({
            "question": tc["question"],
            "expected": tc["expected"],
            "predicted": predicted,
            "correct": is_correct,
        })

    accuracy = correct / total * 100
    print(f"\n{'='*50}")
    print("  Router 路由准确率评估")
    print(f"{'='*50}")
    print(f"  总用例: {total}")
    print(f"  正确:   {correct}")
    print(f"  准确率: {accuracy:.1f}%\n")

    for r in results:
        status = "✅" if r["correct"] else "❌"
        print(f"  {status} [{r['expected']:>20s}] → [{r['predicted']:>20s}]  {r['question']}")

    return accuracy


def eval_workflows():
    from app.agents.workflows.chat_graph import run_chat_workflow
    from app.tools.db import init_agent_tables

    init_agent_tables()

    print(f"\n{'='*50}")
    print("  Workflow 回答质量评估（chat_workflow）")
    print(f"{'='*50}")

    test_questions = [
        "你们平台有什么功能",
        "怎么注册账号",
        "如何上传视频",
        "AI 助手能做什么",
    ]

    for q in test_questions:
        result = run_chat_workflow(q)
        answer = result.get("answer", "") or result.get("response", "") or ""
        has_content = len(answer) > 20
        status = "✅" if has_content else "❌"
        print(f"\n  Q: {q}")
        print(f"  {status} A: {answer[:80]}...")
        print()


if __name__ == "__main__":
    print("ViewHub AI Agent 评测")
    print("=" * 50)

    router_acc = eval_router()

    print()
    input("按 Enter 继续执行 Workflow 评测（需要数据库+LLM）...")

    eval_workflows()

    print(f"\n{'='*50}")
    if router_acc >= 80:
        print(f"  综合评级: ✅ 通过 (路由准确率 {router_acc:.0f}%)")
    else:
        print(f"  综合评级: ⚠️ 需要优化 (路由准确率 {router_acc:.0f}%，目标 ≥80%)")
    print(f"{'='*50}\n")
