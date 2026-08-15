import logging
import json
from typing import Dict, Any, TypedDict
from langgraph.graph import StateGraph
from langgraph.constants import START, END
from app.tools import UserTools
from app.tools.llm_tools import LLM_tools
from app.agents.supervisor import Supervisor
from app.tools.output_guard import FALLBACK_RESPONSE
from app.agents.workflows.harness_helpers import save_checkpoint, invoke_with_governor, checkpoint
from app.harness.checkpoint import CheckpointManager
from app.agents.workflows.constants import WorkflowType

logger = logging.getLogger(__name__)

USER_DATA_STEP_ORDER = ["intent_node", "query_node", "response_node", "supervisor_node"]


class UserDataState(TypedDict):
    question: str
    user_id: str
    session_id: str
    intent: Dict[str, Any]
    query_result: Dict[str, Any]
    response: str
    answer: str
    workflow_type: str


INTENT_MAP = {
    "like_count_today": {"data_type": "like", "time_range": "today", "aggregation": "count"},
    "favorite_count_today": {"data_type": "favorite", "time_range": "today", "aggregation": "count"},
    "like_count_total": {"data_type": "like", "time_range": "all", "aggregation": "count"},
    "favorite_count_total": {"data_type": "favorite", "time_range": "all", "aggregation": "count"},
    "like_list": {"data_type": "like", "time_range": "all", "aggregation": "list"},
    "favorite_list": {"data_type": "favorite", "time_range": "all", "aggregation": "list"},
    "history_list": {"data_type": "history", "time_range": "all", "aggregation": "list"},
    "like_top": {"data_type": "like", "time_range": "all", "aggregation": "top"},
    "week_like_count": {"data_type": "like", "time_range": "week", "aggregation": "count"},
}

INTENT_KEYWORDS = [
    (["今天", "点赞", "多少"], "like_count_today"),
    (["今天", "赞", "多少"], "like_count_today"),
    (["今天", "收藏", "多少"], "favorite_count_today"),
    (["总共", "点赞", "多少"], "like_count_total"),
    (["总共", "赞", "多少"], "like_count_total"),
    (["总共", "收藏", "多少"], "favorite_count_total"),
    (["点赞", "多少"], "like_count_total"),
    (["赞了", "多少"], "like_count_total"),
    (["收藏", "多少"], "favorite_count_total"),
    (["收藏了", "多少"], "favorite_count_total"),
    (["点赞", "哪些"], "like_list"),
    (["收藏", "哪些"], "favorite_list"),
    (["播放历史", "历史"], "history_list"),
    (["看过", "哪些", "视频"], "history_list"),
    (["点赞", "最多"], "like_top"),
    (["本周", "点赞"], "week_like_count"),
    (["这周", "点赞"], "week_like_count"),
]


def _parse_intent_keywords(question: str) -> str:
    for keywords, intent in INTENT_KEYWORDS:
        if all(k in question for k in keywords):
            return intent
    return ""


@checkpoint("intent_node")
def intent_node(state: UserDataState) -> dict:
    question = state.get("question", "")
    sid = state.get("session_id", "")

    intent_key = _parse_intent_keywords(question)
    if not intent_key:
        def _llm_intent():
            messages = [
                {"role": "system", "content": "你是一个意图识别助手。根据用户的问题，判断用户想查什么用户数据。"
                 "只返回以下 JSON 格式之一，不要解释：\n"
                 '- {"data_type": "like", "time_range": "today", "aggregation": "count"}\n'
                 '- {"data_type": "like", "time_range": "all", "aggregation": "count"}\n'
                 '- {"data_type": "like", "time_range": "all", "aggregation": "list"}\n'
                 '- {"data_type": "like", "time_range": "all", "aggregation": "top"}\n'
                 '- {"data_type": "favorite", "time_range": "today", "aggregation": "count"}\n'
                 '- {"data_type": "favorite", "time_range": "all", "aggregation": "count"}\n'
                 '- {"data_type": "favorite", "time_range": "all", "aggregation": "list"}\n'
                 '- {"data_type": "history", "time_range": "all", "aggregation": "list"}\n'
                 '- {"data_type": "like", "time_range": "week", "aggregation": "count"}'},
                {"role": "user", "content": question}
            ]
            return LLM_tools.chat_sync_json(messages, temperature=0, max_tokens=200)

        result = invoke_with_governor(sid, WorkflowType.USER_DATA, "intent_classify", _llm_intent)
        if result and isinstance(result, dict):
            intent = result
        else:
            intent = {"data_type": "unknown", "time_range": "all", "aggregation": "unknown"}
    else:
        intent = INTENT_MAP[intent_key]

    return {"intent": intent}


@checkpoint("query_node")
def query_node(state: UserDataState) -> dict:
    intent = state.get("intent", {})
    user_id = state.get("user_id", "")
    sid = state.get("session_id", "")
    data_type = intent.get("data_type", "")
    time_range = intent.get("time_range", "")
    aggregation = intent.get("aggregation", "")

    if not user_id:
        return {"query_result": {"error": "未获取到用户信息"}}

    def _execute_query():
        if data_type == "like" and aggregation == "count":
            if time_range == "today":
                count = UserTools.get_today_like_count(user_id)
                return {"count": count, "summary_text": f"你今天共点赞了 {count} 次"}
            elif time_range == "week":
                count = UserTools.get_week_like_count(user_id)
                return {"count": count, "summary_text": f"你这周共点赞了 {count} 次"}
            else:
                count = UserTools.get_total_like_count(user_id)
                return {"count": count, "summary_text": f"你共点赞了 {count} 次"}

        elif data_type == "favorite" and aggregation == "count":
            if time_range == "today":
                count = UserTools.get_today_favorite_count(user_id)
                return {"count": count, "summary_text": f"你今天共收藏了 {count} 次"}
            else:
                count = UserTools.get_total_favorite_count(user_id)
                return {"count": count, "summary_text": f"你共收藏了 {count} 次"}

        elif data_type == "like" and aggregation == "list":
            result_data = UserTools.get_recent_liked_videos(user_id)
            videos = result_data.get("videos", [])
            total = result_data.get("total", 0)
            video_names = [v.get("video_name", "未知视频") for v in videos[:10]]
            summary = f"你共点赞了 {total} 个视频"
            if video_names:
                summary += "，最近点赞：\n" + "\n".join(f"- {name}" for name in video_names)
            else:
                summary += "，还没有点赞过视频"
            return {"videos": video_names, "total": total, "summary_text": summary}

        elif data_type == "favorite" and aggregation == "list":
            result_data = UserTools.get_recent_favorites(user_id)
            videos = result_data.get("videos", [])
            total = result_data.get("total", 0)
            video_names = [v.get("video_name", "未知视频") for v in videos[:10]]
            summary = f"你共收藏了 {total} 个视频"
            if video_names:
                summary += "，最近收藏：\n" + "\n".join(f"- {name}" for name in video_names)
            else:
                summary += "，还没有收藏过视频"
            return {"videos": video_names, "total": total, "summary_text": summary}

        elif data_type == "history" and aggregation == "list":
            result_data = UserTools.get_recent_history(user_id)
            videos = result_data.get("videos", [])
            total = result_data.get("total", 0)
            video_names = [v.get("video_name", "未知视频") for v in videos[:10]]
            summary = f"你共观看了 {total} 个视频"
            if video_names:
                summary += "，最近观看：\n" + "\n".join(f"- {name}" for name in video_names)
            else:
                summary += "，还没有播放记录"
            return {"videos": video_names, "total": total, "summary_text": summary}

        elif data_type == "like" and aggregation == "top":
            top_videos = UserTools.get_top_liked_videos(user_id)
            if top_videos:
                parts = []
                for v in top_videos[:3]:
                    name = v.get("video_name", "未知视频")
                    cnt = v.get("count", 0)
                    parts.append(f"《{name}》（{cnt}次）")
                summary = "你点赞最多的视频：\n" + "\n".join(f"{i+1}. {p}" for i, p in enumerate(parts))
            else:
                summary = "还没有点赞过视频"
            return {"videos": top_videos, "summary_text": summary}

        return {"error": "无法识别查询意图", "summary_text": FALLBACK_RESPONSE}

    query_result = invoke_with_governor(sid, WorkflowType.USER_DATA, "user_data_query", _execute_query)
    if not query_result:
        query_result = {"error": "工具调用失败", "summary_text": FALLBACK_RESPONSE}

    return {"query_result": query_result}


@checkpoint("response_node")
def response_node(state: UserDataState) -> dict:
    query_result = state.get("query_result", {})
    summary_text = query_result.get("summary_text", "")

    if query_result.get("error"):
        return {"response": summary_text, "answer": summary_text}

    question = state.get("question", "")
    messages = [
        {"role": "system", "content": "你是一个温柔友好的用户数据查询助手。根据查询结果，用自然语言回答用户。"
         "回答要简洁亲切，直接告诉用户结果。如果数据为空，用鼓励的语气。不要添加查询结果中没有的信息。"},
        {"role": "user", "content": f"用户问题：{question}\n\n查询结果：{summary_text}"}
    ]

    result_text = LLM_tools.chat_sync(messages, temperature=0.3)
    if not result_text:
        result_text = summary_text

    return {"response": result_text, "answer": result_text}


@checkpoint("supervisor_node")
def supervisor_node(state: UserDataState) -> dict:
    outputs = {
        "intent": state.get("intent", {}),
        "query_result": state.get("query_result", {}),
        "response": state.get("response", "")
    }
    answer = Supervisor().aggregate(outputs, WorkflowType.USER_DATA)
    return {"answer": answer}


def build_user_data_graph():
    builder = StateGraph(UserDataState)

    builder.add_node("intent_node", intent_node)
    builder.add_node("query_node", query_node)
    builder.add_node("response_node", response_node)
    builder.add_node("supervisor_node", supervisor_node)

    builder.add_edge(START, "intent_node")
    builder.add_edge("intent_node", "query_node")
    builder.add_edge("query_node", "response_node")
    builder.add_edge("response_node", "supervisor_node")
    builder.add_edge("supervisor_node", END)

    return builder.compile()


user_data_graph = build_user_data_graph()


def run_user_data_workflow(question: str, user_id: str = None,
                           session_id: str = None) -> Dict[str, Any]:
    initial_state: UserDataState = {
        "question": question,
        "user_id": user_id or "",
        "session_id": session_id or "",
        "intent": {},
        "query_result": {},
        "response": "",
        "answer": "",
        "workflow_type": WorkflowType.USER_DATA
    }

    try:
        result = user_data_graph.invoke(initial_state)
    except Exception as e:
        logger.error(f"user_data_graph 执行失败: {e}")
        return {
            "answer": FALLBACK_RESPONSE,
            "intent": {},
            "query_result": {},
            "workflow_type": WorkflowType.USER_DATA
        }

    return {
        "answer": result.get("answer", ""),
        "intent": result.get("intent", {}),
        "query_result": result.get("query_result", {}),
        "workflow_type": WorkflowType.USER_DATA
    }


def resume_user_data_workflow(session_id: str) -> Dict[str, Any]:
    """从最近一次 checkpoint 恢复 user_data workflow"""
    mgr = CheckpointManager()
    last_cp = mgr.get_last_completed(session_id, WorkflowType.USER_DATA)
    if not last_cp:
        return {"answer": "", "error": "无可用 checkpoint", "workflow_type": WorkflowType.USER_DATA}

    completed_step = last_cp.step_name
    state = last_cp.state_snapshot

    if completed_step == "supervisor_node":
        return {
            "answer": state.get("answer", ""),
            "intent": state.get("intent", {}),
            "query_result": state.get("query_result", {}),
            "workflow_type": WorkflowType.USER_DATA,
            "resumed_from": completed_step,
        }

    next_idx = USER_DATA_STEP_ORDER.index(completed_step) + 1 if completed_step in USER_DATA_STEP_ORDER else 0
    remaining_steps = USER_DATA_STEP_ORDER[next_idx:]

    step_fn_map = {
        "query_node": query_node,
        "response_node": response_node,
        "supervisor_node": supervisor_node,
    }

    for step_name in remaining_steps:
        step_fn = step_fn_map.get(step_name)
        if step_fn:
            try:
                step_result = step_fn(state)
                state.update(step_result)
            except Exception as e:
                save_checkpoint(session_id, WorkflowType.USER_DATA, step_name, state, status="failed", error=str(e))
                return {"answer": state.get("answer", ""), "error": str(e),
                        "workflow_type": WorkflowType.USER_DATA, "failed_at": step_name}

    return {
        "answer": state.get("answer", ""),
        "intent": state.get("intent", {}),
        "query_result": state.get("query_result", {}),
        "workflow_type": WorkflowType.USER_DATA,
        "resumed_from": completed_step,
    }
