import logging
from typing import Any, Dict, List, Tuple, TypedDict

from langgraph.constants import END, START
from langgraph.graph import StateGraph

from app.agents.supervisor import Supervisor
from app.agents.workflows.constants import WorkflowType
from app.agents.workflows.harness_helpers import checkpoint, invoke_with_governor, save_checkpoint
from app.config import build_cover_url
from app.harness.checkpoint import CheckpointManager
from app.tools import UserTools, VideoTools
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
    (["今天", "点赞"], "like_list_today"),
    (["今日", "点赞"], "like_list_today"),
    (["今天", "收藏"], "favorite_list_today"),
    (["今日", "收藏"], "favorite_list_today"),
    (["今天", "播放历史"], "history_today"),
    (["今日", "播放历史"], "history_today"),
    (["今天", "观看记录"], "history_today"),
    (["今日", "观看记录"], "history_today"),
    (["今天", "浏览记录"], "history_today"),
    (["今日", "浏览记录"], "history_today"),
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
            return f"，这里只列出最近 {shown} 个："
        return "："
    return all_time_lead.rstrip("\n")


def _clip_intro(text: str, limit: int = 100) -> str:
    s = " ".join((text or "").split())
    if not s:
        return ""
    if len(s) <= limit:
        return s
    return s[:limit].rstrip() + "…"


def _display_name(raw: Any) -> str:
    name = (raw or "").strip() if isinstance(raw, str) else ""
    return name or "未知视频"


def _cards_from_user_videos(
    raw: List[Dict[str, Any]],
    fallback_reason: str = "",
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """把点赞/收藏/历史名单转成和推荐流一样的卡片字段。"""
    shown = [v for v in (raw or [])[:10] if isinstance(v, dict)]
    ids = [str(v.get("video_id")) for v in shown if v.get("video_id")]
    infos = []
    if ids:
        try:
            infos = VideoTools.get_video_info_batch(ids) or []
        except Exception:
            infos = []
    by_id = {vi.videoId: vi for vi in infos if vi and getattr(vi, "videoId", None)}
    cards: List[Dict[str, Any]] = []
    reasons: List[str] = []
    for v in shown:
        vid = v.get("video_id") or ""
        name = _display_name(v.get("video_name"))
        vi = by_id.get(vid)
        title = name
        cover = ""
        intro = ""
        author = ""
        if vi:
            title = _display_name(vi.videoName or name)
            cover = build_cover_url(vi.videoCover) if vi.videoCover else ""
            intro = _clip_intro(vi.introduction or "")
            author = vi.nickName or ""
        count = v.get("count")
        reason = intro
        if not reason and count:
            reason = f"点赞 {count} 次"
        if not reason:
            reason = fallback_reason
        cards.append({
            "video_id": vid,
            "title": title,
            "cover": cover,
            "author": author,
        })
        reasons.append(reason)
    return cards, reasons


def _pack_user_data_result(state: Dict[str, Any], **extra: Any) -> Dict[str, Any]:
    query_result = state.get("query_result") or {}
    videos = query_result.get("videos") or []
    if videos and isinstance(videos[0], str):
        videos = []
    reasons = query_result.get("reasons") or []
    packed = {
        "answer": state.get("answer", ""),
        "intent": state.get("intent", {}),
        "query_result": query_result,
        "recommended_videos": videos if isinstance(videos, list) else [],
        "reasons": reasons if isinstance(reasons, list) else [],
        "workflow_type": WorkflowType.USER_DATA,
    }
    packed.update(extra)
    return packed


_ALL_TIME_WHEN_PERIOD = {
    "like_list", "favorite_list", "history_list",
    "like_count_total", "favorite_count_total", "like_top",
}


def _parse_intent_keywords(question: str) -> str:
    today = any(k in question for k in ("今天", "今日"))
    week = any(k in question for k in ("这周", "本周"))
    for keywords, intent in INTENT_KEYWORDS:
        if all(k in question for k in keywords):
            # 「观看」是「观看量」的子串，当前视频播放量不能当成今日观看历史。
            if intent.startswith("history") and "观看" in keywords and "观看量" in question:
                continue
            # 「我今天的点赞」会命中靠后的「我的点赞」全量列表，有时间词时跳过累计意图。
            if (today or week) and intent in _ALL_TIME_WHEN_PERIOD:
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
            cards, reasons = _cards_from_user_videos(videos, fallback_reason="你最近点过这个")
            if time_range == "today":
                summary = f"你今天点赞了 {total} 个视频"
                empty = "，今天还没有点赞过视频"
            elif time_range == "week":
                summary = f"你这周点赞了 {total} 个视频"
                empty = "，这周还没有点赞过视频"
            else:
                summary = f"你共点赞了 {total} 个视频"
                empty = "，还没有点赞过视频"
            if cards:
                summary += _list_lead(time_range, total, len(cards), "，最近点赞：")
            else:
                summary += empty
            return {"videos": cards, "reasons": reasons, "total": total, "summary_text": summary}

        elif data_type == "favorite" and aggregation == "list":
            result_data = UserTools.get_recent_favorites(user_id, time_range=time_range or "all")
            videos = result_data.get("videos", [])
            total = result_data.get("total", 0)
            cards, reasons = _cards_from_user_videos(videos, fallback_reason="你最近收藏过")
            if time_range == "today":
                summary = f"你今天收藏了 {total} 个视频"
                empty = "，今天还没有收藏过视频"
            elif time_range == "week":
                summary = f"你这周收藏了 {total} 个视频"
                empty = "，这周还没有收藏过视频"
            else:
                summary = f"你共收藏了 {total} 个视频"
                empty = "，还没有收藏过视频"
            if cards:
                summary += _list_lead(time_range, total, len(cards), "，最近收藏：")
            else:
                summary += empty
            return {"videos": cards, "reasons": reasons, "total": total, "summary_text": summary}

        elif data_type == "history" and aggregation == "list":
            result_data = UserTools.get_recent_history(user_id, time_range=time_range or "all")
            videos = result_data.get("videos", [])
            total = result_data.get("total", 0)
            cards, reasons = _cards_from_user_videos(videos, fallback_reason="你最近看过")
            if time_range == "today":
                summary = f"你今天看了 {total} 个视频"
                empty = "，今天还没有播放记录"
            elif time_range == "week":
                summary = f"你这周看了 {total} 个视频"
                empty = "，这周还没有播放记录"
            else:
                summary = f"你共观看了 {total} 个视频"
                empty = "，还没有播放记录"
            if cards:
                summary += _list_lead(time_range, total, len(cards), "，最近观看：")
            else:
                summary += empty
            return {"videos": cards, "reasons": reasons, "total": total, "summary_text": summary}

        elif data_type == "like" and aggregation == "top":
            top_videos = UserTools.get_top_liked_videos(user_id)
            cards, reasons = _cards_from_user_videos(top_videos[:3], fallback_reason="")
            if cards:
                summary = "你点赞最多的视频："
            else:
                summary = "还没有点赞过视频"
            return {"videos": cards, "reasons": reasons, "summary_text": summary}

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
            "recommended_videos": [],
            "reasons": [],
            "workflow_type": WorkflowType.USER_DATA
        }

    return _pack_user_data_result(result)


def resume_user_data_workflow(session_id: str) -> Dict[str, Any]:
    """从最近一次 checkpoint 恢复 user_data workflow"""
    mgr = CheckpointManager()
    last_cp = mgr.get_last_completed(session_id, WorkflowType.USER_DATA)
    if not last_cp:
        return {"answer": "", "error": "无可用 checkpoint", "workflow_type": WorkflowType.USER_DATA}

    completed_step = last_cp.step_name
    state = last_cp.state_snapshot

    if completed_step == "supervisor_node":
        return _pack_user_data_result(state, resumed_from=completed_step)

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

    return _pack_user_data_result(state, resumed_from=completed_step)
