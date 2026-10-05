import logging
from typing import Any, Dict, TypedDict

from langgraph.constants import END, START
from langgraph.graph import StateGraph

from app.agents.supervisor import Supervisor
from app.agents.workflows.constants import WorkflowType
from app.agents.workflows.harness_helpers import checkpoint, invoke_with_governor, save_checkpoint
from app.harness.checkpoint import CheckpointManager
from app.tools import UserTools
from app.tools.llm_tools import LLM_tools
from app.tools.output_guard import FALLBACK_RESPONSE

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
    "favorite_count_week": {"data_type": "favorite", "time_range": "week", "aggregation": "count"},
    "like_count_total": {"data_type": "like", "time_range": "all", "aggregation": "count"},
    "favorite_count_total": {"data_type": "favorite", "time_range": "all", "aggregation": "count"},
    "like_list": {"data_type": "like", "time_range": "all", "aggregation": "list"},
    "like_list_today": {"data_type": "like", "time_range": "today", "aggregation": "list"},
    "like_list_week": {"data_type": "like", "time_range": "week", "aggregation": "list"},
    "favorite_list": {"data_type": "favorite", "time_range": "all", "aggregation": "list"},
    "favorite_list_today": {"data_type": "favorite", "time_range": "today", "aggregation": "list"},
    "favorite_list_week": {"data_type": "favorite", "time_range": "week", "aggregation": "list"},
    "history_list": {"data_type": "history", "time_range": "all", "aggregation": "list"},
    "history_today": {"data_type": "history", "time_range": "today", "aggregation": "list"},
    "history_week": {"data_type": "history", "time_range": "week", "aggregation": "list"},
    "like_top": {"data_type": "like", "time_range": "all", "aggregation": "top"},
    "week_like_count": {"data_type": "like", "time_range": "week", "aggregation": "count"},
    "coin_count": {"data_type": "coin", "time_range": "all", "aggregation": "count"},
    "following_list": {"data_type": "follow", "time_range": "all", "aggregation": "list"},
}

INTENT_KEYWORDS = [
    (["今天", "点赞", "多少"], "like_count_today"),
    (["今日", "点赞", "多少"], "like_count_today"),
    (["今天", "赞", "多少"], "like_count_today"),
    (["今日", "赞", "多少"], "like_count_today"),
    (["这周", "点赞", "多少"], "week_like_count"),
    (["本周", "点赞", "多少"], "week_like_count"),
    (["这周", "赞", "多少"], "week_like_count"),
    (["本周", "赞", "多少"], "week_like_count"),
    (["今天", "收藏", "多少"], "favorite_count_today"),
    (["今日", "收藏", "多少"], "favorite_count_today"),
    (["这周", "收藏", "多少"], "favorite_count_week"),
    (["本周", "收藏", "多少"], "favorite_count_week"),
    (["今天", "看了"], "history_today"),
    (["今日", "看了"], "history_today"),
    (["今天", "看过"], "history_today"),
    (["今日", "看过"], "history_today"),
    (["今天", "观看"], "history_today"),
    (["今日", "观看"], "history_today"),
    (["这周", "看了"], "history_week"),
    (["这周", "看过"], "history_week"),
    (["这周", "观看"], "history_week"),
    (["本周", "看了"], "history_week"),
    (["本周", "看过"], "history_week"),
    (["本周", "观看"], "history_week"),
    (["总共", "点赞", "多少"], "like_count_total"),
    (["总共", "赞", "多少"], "like_count_total"),
    (["总共", "收藏", "多少"], "favorite_count_total"),
    (["点赞", "多少"], "like_count_total"),
    (["赞了", "多少"], "like_count_total"),
    (["收藏", "多少"], "favorite_count_total"),
    (["收藏了", "多少"], "favorite_count_total"),
    (["今天", "点赞", "哪些"], "like_list_today"),
    (["今日", "点赞", "哪些"], "like_list_today"),
    (["今天", "收藏", "哪些"], "favorite_list_today"),
    (["今日", "收藏", "哪些"], "favorite_list_today"),
    (["这周", "点赞", "哪些"], "like_list_week"),
    (["本周", "点赞", "哪些"], "like_list_week"),
    (["这周", "收藏", "哪些"], "favorite_list_week"),
    (["本周", "收藏", "哪些"], "favorite_list_week"),
    (["点赞", "哪些"], "like_list"),
    (["收藏", "哪些"], "favorite_list"),
    (["播放历史", "历史"], "history_list"),
    (["看过", "哪些", "视频"], "history_list"),
    (["看了", "哪些", "视频"], "history_list"),
    (["看了", "什么", "视频"], "history_list"),
    (["看", "哪些", "视频"], "history_list"),
    (["看", "什么", "视频"], "history_list"),
    (["看过", "什么", "视频"], "history_list"),
    (["浏览记录"], "history_list"),
    (["观看记录"], "history_list"),
    (["最近", "播放"], "history_list"),
    (["最近", "看"], "history_list"),
    (["播放过"], "history_list"),
    (["点赞", "最多"], "like_top"),
    (["本周", "点赞"], "week_like_count"),
    (["这周", "点赞"], "week_like_count"),
    (["硬币", "多少"], "coin_count"),
    (["有多少", "硬币"], "coin_count"),
    (["关注", "哪些"], "following_list"),
    (["关注", "up主"], "following_list"),
    (["关注的", "up"], "following_list"),
    (["关注", "了", "谁"], "following_list"),
    (["我的", "点赞"], "like_list"),
    (["点赞过"], "like_list"),
    (["点赞"], "like_list"),
    (["我的", "收藏"], "favorite_list"),
    (["收藏"], "favorite_list"),
]


def _list_lead(time_range: str, total: int, shown: int, all_time_lead: str) -> str:
    """今天/本周只取出一部分时说明被截断。全部时间沿用「最近」。"""
    if time_range in ("today", "week"):
        if shown and total > shown:
            return f"，这里只列出最近 {shown} 个：\n"
        return "：\n"
    return all_time_lead


def _parse_intent_keywords(question: str) -> str:
    for keywords, intent in INTENT_KEYWORDS:
        if all(k in question for k in keywords):
            # 「观看」是「观看量」的子串，当前视频播放量不能当成今日观看历史。
            if intent.startswith("history") and "观看" in keywords and "观看量" in question:
                continue
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
                 '- {"data_type": "like", "time_range": "today", "aggregation": "list"}\n'
                 '- {"data_type": "like", "time_range": "week", "aggregation": "list"}\n'
                 '- {"data_type": "like", "time_range": "all", "aggregation": "list"}\n'
                 '- {"data_type": "like", "time_range": "all", "aggregation": "top"}\n'
                 '- {"data_type": "favorite", "time_range": "today", "aggregation": "count"}\n'
                 '- {"data_type": "favorite", "time_range": "week", "aggregation": "count"}\n'
                 '- {"data_type": "favorite", "time_range": "all", "aggregation": "count"}\n'
                 '- {"data_type": "favorite", "time_range": "today", "aggregation": "list"}\n'
                 '- {"data_type": "favorite", "time_range": "week", "aggregation": "list"}\n'
                 '- {"data_type": "favorite", "time_range": "all", "aggregation": "list"}\n'
                 '- {"data_type": "history", "time_range": "today", "aggregation": "list"}\n'
                 '- {"data_type": "history", "time_range": "week", "aggregation": "list"}\n'
                 '- {"data_type": "history", "time_range": "all", "aggregation": "list"}\n'
                 '- {"data_type": "like", "time_range": "week", "aggregation": "count"}\n'
                 '- {"data_type": "coin", "time_range": "all", "aggregation": "count"}\n'
                 '- {"data_type": "follow", "time_range": "all", "aggregation": "list"}'},
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
            elif time_range == "week":
                count = UserTools.get_week_favorite_count(user_id)
                return {"count": count, "summary_text": f"你这周共收藏了 {count} 次"}
            else:
                count = UserTools.get_total_favorite_count(user_id)
                return {"count": count, "summary_text": f"你共收藏了 {count} 次"}

        elif data_type == "like" and aggregation == "list":
            result_data = UserTools.get_recent_liked_videos(user_id, time_range=time_range or "all")
            videos = result_data.get("videos", [])
            total = result_data.get("total", 0)
            video_names = [v.get("video_name") or "未知视频" for v in videos[:10]]
            if time_range == "today":
                summary = f"你今天点赞了 {total} 个视频"
                empty = "，今天还没有点赞过视频"
            elif time_range == "week":
                summary = f"你这周点赞了 {total} 个视频"
                empty = "，这周还没有点赞过视频"
            else:
                summary = f"你共点赞了 {total} 个视频"
                empty = "，还没有点赞过视频"
            lead = _list_lead(time_range, total, len(video_names), "，最近点赞：\n")
            if video_names:
                summary += lead + "\n".join(f"- {name}" for name in video_names)
            else:
                summary += empty
            return {"videos": video_names, "total": total, "summary_text": summary}

        elif data_type == "favorite" and aggregation == "list":
            result_data = UserTools.get_recent_favorites(user_id, time_range=time_range or "all")
            videos = result_data.get("videos", [])
            total = result_data.get("total", 0)
            video_names = [v.get("video_name") or "未知视频" for v in videos[:10]]
            if time_range == "today":
                summary = f"你今天收藏了 {total} 个视频"
                empty = "，今天还没有收藏过视频"
            elif time_range == "week":
                summary = f"你这周收藏了 {total} 个视频"
                empty = "，这周还没有收藏过视频"
            else:
                summary = f"你共收藏了 {total} 个视频"
                empty = "，还没有收藏过视频"
            lead = _list_lead(time_range, total, len(video_names), "，最近收藏：\n")
            if video_names:
                summary += lead + "\n".join(f"- {name}" for name in video_names)
            else:
                summary += empty
            return {"videos": video_names, "total": total, "summary_text": summary}

        elif data_type == "history" and aggregation == "list":
            result_data = UserTools.get_recent_history(user_id, time_range=time_range or "all")
            videos = result_data.get("videos", [])
            total = result_data.get("total", 0)
            video_names = [v.get("video_name") or "未知视频" for v in videos[:10]]
            if time_range == "today":
                summary = f"你今天看了 {total} 个视频"
                empty = "，今天还没有播放记录"
            elif time_range == "week":
                summary = f"你这周看了 {total} 个视频"
                empty = "，这周还没有播放记录"
            else:
                summary = f"你共观看了 {total} 个视频"
                empty = "，还没有播放记录"
            if video_names:
                lead = _list_lead(time_range, total, len(video_names), "，最近观看：\n")
                summary += lead + "\n".join(f"- {name}" for name in video_names)
            else:
                summary += empty
            return {"videos": video_names, "total": total, "summary_text": summary}

        elif data_type == "like" and aggregation == "top":
            top_videos = UserTools.get_top_liked_videos(user_id)
            if top_videos:
                parts = []
                for v in top_videos[:3]:
                    name = v.get("video_name") or "未知视频"
                    cnt = v.get("count", 0)
                    parts.append(f"《{name}》（{cnt}次）")
                summary = "你点赞最多的视频：\n" + "\n".join(f"{i+1}. {p}" for i, p in enumerate(parts))
            else:
                summary = "还没有点赞过视频"
            return {"videos": top_videos, "summary_text": summary}

        elif data_type == "coin" and aggregation == "count":
            count = UserTools.get_coin_count(user_id)
            return {"count": count, "summary_text": f"你当前共有 {count} 枚硬币"}

        elif data_type == "follow" and aggregation == "list":
            result_data = UserTools.get_followings(user_id)
            users = result_data.get("users", [])
            total = result_data.get("total", 0)
            names = [u.get("nick_name", "未知用户") for u in users[:10]]
            summary = f"你共关注了 {total} 位 up 主"
            if names:
                summary += "，最近关注：\n" + "\n".join(f"- {name}" for name in names)
            else:
                summary += "，还没有关注任何人"
            return {"users": users, "total": total, "summary_text": summary}

        return {"error": "unsupported_query", "summary_text": "ViewHub 目前暂不支持查询这类信息。你可以问我点赞、收藏、观看历史、关注列表、投币数等。"}

    query_result = invoke_with_governor(sid, WorkflowType.USER_DATA, "user_data_query", _execute_query)
    if not query_result:
        query_result = {"error": "工具调用失败", "summary_text": FALLBACK_RESPONSE}

    return {"query_result": query_result}


@checkpoint("response_node")
def response_node(state: UserDataState) -> dict:
    """点赞、收藏、硬币等查询已经有确定的 summary_text，直接返回，不再交给模型改写数字。"""
    query_result = state.get("query_result", {})
    summary_text = query_result.get("summary_text", "") or ""
    if summary_text:
        return {"response": summary_text, "answer": summary_text}
    return {"response": FALLBACK_RESPONSE, "answer": FALLBACK_RESPONSE}


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
