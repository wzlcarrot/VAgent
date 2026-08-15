import logging
from typing import Dict, Any, List, TypedDict, Literal
from langgraph.graph import StateGraph
from langgraph.constants import START, END
from app.tools import UserTools, VideoTools
from app.agents.supervisor import Supervisor
from app.tools.output_guard import NO_RECOMMENDATION_MSG
from app.config import build_cover_url
from app.agents.workflows.harness_helpers import save_checkpoint, invoke_with_governor, checkpoint
from app.harness.checkpoint import CheckpointManager
from app.agents.workflows.constants import WorkflowType

logger = logging.getLogger(__name__)

RECOMMEND_STEP_ORDER = ["profile_node", "search_node", "reason_node", "summary_node", "supervisor_node"]
RECOMMEND_COLD_START_ORDER = ["profile_node", "cold_start_node", "supervisor_node"]


def _build_recommend_markdown(videos: List[Dict[str, Any]], reasons: List[str] = None) -> str:
    """推荐结果生成纯 Markdown 文本（标题/封面/关键词/作者/创建时间/播放量/理由）。

    替代"text 文本 + videos 卡片"双通道：信息全部由文本承载，避免冗余。
    """
    if not videos:
        return ""
    reasons = reasons or []
    blocks = []
    for i, v in enumerate(videos):
        title = v.get("title", "未知视频")
        cover = v.get("cover", "")
        tags = v.get("tags", "") or []
        author = v.get("author", "")
        create_time = v.get("create_time", "") or ""
        play_count = v.get("play_count", 0)
        reason = reasons[i] if i < len(reasons) else ""

        lines = [f"## {i+1}. {title}"]
        if cover:
            lines.append(f"![{title}]({cover})")
        meta = []
        if tags:
            tag_str = " · ".join([t.strip() for t in str(tags).split(",") if t.strip()][:3]) if isinstance(tags, str) else " · ".join(tags[:3])
            if tag_str:
                meta.append(f"关键词：{tag_str}")
        if author:
            meta.append(f"作者：{author}")
        if create_time:
            meta.append(f"创建时间：{str(create_time)[:10]}")
        if play_count:
            meta.append(f"播放量：{play_count}次")
        if reason:
            meta.append(f"推荐理由：{reason}")
        if meta:
            lines.append("\n".join(meta))
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


class RecommendState(TypedDict):
    user_id: str
    question: str
    session_id: str
    top_k: int
    user_profile: Dict[str, Any]
    candidate_videos: List[Dict[str, Any]]
    recommended_videos: List[Dict[str, Any]]
    reasons: List[str]
    summary: str
    answer: str
    workflow_type: str


def _save_checkpoint(session_id: str, step_name: str, state: Dict[str, Any],
                     result: Dict[str, Any] = None, status: str = "completed",
                     error: str = None):
    save_checkpoint(session_id, WorkflowType.RECOMMEND, step_name, state, result, status, error)


@checkpoint("profile_node")
def profile_node(state: RecommendState) -> dict:
    user_id = state.get("user_id")
    if not user_id:
        return {"user_profile": {}}

    play_history = UserTools.get_play_history(user_id, limit=50)
    favorites = UserTools.get_favorites(user_id, limit=50)
    liked = UserTools.get_liked_videos(user_id, limit=50)

    tags = []
    watched_ids = []
    for h in play_history:
        if h.videoId:
            watched_ids.append(h.videoId)
            if h.videoName:
                tags.extend(h.videoName.split())

    return {
        "user_profile": {
            "favorite_tags": list(set(tags))[:10],
            "watched_video_ids": watched_ids,
            "liked_video_ids": liked,
            "favorite_video_ids": favorites,
            "play_count": len(play_history)
        }
    }


@checkpoint("search_node")
def search_node(state: RecommendState) -> dict:
    user_profile = state.get("user_profile", {})
    favorite_tags = user_profile.get("favorite_tags", [])
    question = (state.get("question") or "").strip()
    sid = state.get("session_id", "")

    if not favorite_tags and not question:
        return {"candidate_videos": []}

    if question:
        query_parts = [question]
        if favorite_tags:
            query_parts.extend(favorite_tags[:3])
        query = " ".join(query_parts)
    else:
        query = " ".join(favorite_tags[:5])
    from app.tools.ranker import dual_recall_and_rerank
    results = invoke_with_governor(
        sid, WorkflowType.RECOMMEND, "vector_search",
        lambda: dual_recall_and_rerank(query, top_k=min(state.get("top_k", 5) + 3, 10))
    )

    candidate_videos = []
    seen_ids = set()
    for r in results:
        video_id = r.get("video_id")
        if video_id and video_id not in seen_ids:
            seen_ids.add(video_id)
            candidate_videos.append(video_id)

    if not candidate_videos:
        return {"candidate_videos": []}

    watched = set(user_profile.get("watched_video_ids", []))
    top_k = state.get("top_k", 5)
    candidate_ids = [vid for vid in candidate_videos if vid not in watched][:min(top_k + 3, 10)]

    if not candidate_ids:
        return {"candidate_videos": []}

    video_infos = invoke_with_governor(
        sid, WorkflowType.RECOMMEND, "recommend_videos",
        lambda: VideoTools.get_video_info_batch(candidate_ids)
    )
    video_map = {v.videoId: v for v in video_infos if v}
    if not video_map:
        logger.warning(f"批量获取视频信息失败，无法构建推荐列表")
        return {"candidate_videos": []}

    result_videos = []
    for vid in candidate_ids:
        vi = video_map.get(vid)
        if vi:
            result_videos.append({
                "video_id": vi.videoId,
                "title": vi.videoName,
                "cover": build_cover_url(vi.videoCover) if vi.videoCover else "",
                "author": vi.nickName,
                "tags": vi.tags,
                "create_time": str(vi.createTime) if vi.createTime else "",
                "play_count": vi.playCount or 0
            })

    return {"candidate_videos": result_videos}


@checkpoint("reason_node")
def reason_node(state: RecommendState) -> dict:
    candidate_videos = state.get("candidate_videos", [])
    top_k = state.get("top_k", 5)

    reasons = []
    for video in candidate_videos[:top_k]:
        title = video.get("title", "")
        tags = video.get("tags", "")
        author = video.get("author", "")
        create_time = video.get("create_time", "") or ""

        # 用视频元数据拼接自然推荐理由，优先级：标签 > 作者 > 时间
        parts = []
        if tags:
            tag_list = [t.strip() for t in str(tags).split(",") if t.strip()][:3]
            if tag_list:
                parts.append(" · ".join(tag_list))
        if author:
            parts.append(f"作者 {author}")
        if create_time:
            try:
                dt = create_time[:10]
                parts.append(f"发布于 {dt}")
            except Exception:
                pass
        if parts:
            reasons.append("  ".join(parts))
        elif title:
            reasons.append(f"《{title}》值得一看")
        else:
            reasons.append("")

    return {
        "recommended_videos": candidate_videos[:top_k],
        "reasons": reasons
    }


def has_history_router(state: RecommendState) -> Literal["search_node", "summary_node"]:
    user_profile = state.get("user_profile", {})
    play_count = user_profile.get("play_count", 0)
    if play_count > 0:
        return "search_node"
    return "summary_node"


@checkpoint("summary_node")
def summary_node(state: RecommendState) -> dict:
    recommended_videos = state.get("recommended_videos", [])
    reasons = state.get("reasons", [])

    if not recommended_videos:
        summary = NO_RECOMMENDATION_MSG + "你可以多观看一些视频，我会更好地了解你的偏好。"
        return {"summary": summary, "answer": summary}

    result_text = _build_recommend_markdown(recommended_videos, reasons)

    return {"summary": result_text, "answer": result_text}


@checkpoint("cold_start_node")
def cold_start_node(state: RecommendState) -> dict:
    question = (state.get("question") or "").strip()
    sid = state.get("session_id", "")

    if question:
        top_k = state.get("top_k", 5)
        from app.tools.ranker import dual_recall_and_rerank
        results = invoke_with_governor(
            sid, WorkflowType.RECOMMEND, "vector_search",
            lambda: dual_recall_and_rerank(question, top_k=min(top_k + 3, 10))
        )
        recommended = []
        seen_ids = set()
        rag_intro: dict = {}
        for r in results:
            video_id = r.get("video_id")
            rag_intro[video_id] = r.get("content", "") or ""
            if video_id and video_id not in seen_ids:
                seen_ids.add(video_id)
                recommended.append({
                    "video_id": video_id,
                    "title": r.get("video_name", "未知视频"),
                    "cover": "",
                    "author": "",
                    "tags": ""
                })
        # 补全封面/作者/时间/播放量：RAG 检索结果无这些字段，批量查 video_info 填充
        if recommended:
            video_ids = [v["video_id"] for v in recommended]
            info_map = {v.videoId: v for v in VideoTools.get_video_info_batch(video_ids) if v.videoId}
            for v in recommended:
                info = info_map.get(v["video_id"])
                if info:
                    v["cover"] = build_cover_url(info.videoCover) if info.videoCover else ""
                    v["author"] = info.nickName or ""
                    v["create_time"] = str(info.createTime) if info.createTime else ""
                    v["play_count"] = info.playCount or 0
        if recommended:
            reasons = []
            for v in recommended[:top_k]:
                title = v.get("title", "")
                intro = rag_intro.get(v["video_id"], "")[:60].replace("\n", " ")
                if intro and intro != title:
                    reasons.append(f"「{intro}」")
                elif title:
                    reasons.append(f"《{title}》值得一看")
                else:
                    reasons.append("")
            summary = _build_recommend_markdown(recommended[:top_k], reasons)
            return {
                "recommended_videos": recommended[:top_k],
                "reasons": reasons,
                "summary": summary,
                "answer": summary
            }

    recent = VideoTools.get_recent_videos(limit=10)
    recommended = []
    for v in recent:
        recommended.append({
            "video_id": v.videoId,
            "title": v.videoName,
            "cover": build_cover_url(v.videoCover) if v.videoCover else "",
            "author": v.nickName,
            "tags": v.tags,
            "create_time": str(v.createTime) if v.createTime else "",
            "play_count": v.playCount or 0
        })

    top_k = state.get("top_k", 5)
    reasons = []
    for v in recommended[:top_k]:
        title = v.get("title", "")
        tags = v.get("tags", "")
        author = v.get("author", "")
        create_time = v.get("create_time", "") or ""

        parts = []
        if tags:
            tag_list = [t.strip() for t in str(tags).split(",") if t.strip()][:3]
            if tag_list:
                parts.append(" · ".join(tag_list))
        if author:
            parts.append(f"作者 {author}")
        if create_time:
            try:
                dt = create_time[:10]
                parts.append(f"发布于 {dt}")
            except Exception:
                pass
        if parts:
            reasons.append("  ".join(parts))
        elif title:
            reasons.append(f"《{title}》值得一看")
        else:
            reasons.append("")
    summary = _build_recommend_markdown(recommended[:top_k], reasons)

    return {
        "recommended_videos": recommended[:top_k],
        "reasons": reasons,
        "summary": summary,
        "answer": summary
    }


@checkpoint("supervisor_node")
def supervisor_node(state: RecommendState) -> dict:
    outputs = {
        "user_profile": state.get("user_profile", {}),
        "recommended_videos": state.get("recommended_videos", []),
        "reasons": state.get("reasons", []),
        "answer": state.get("summary", "")
    }
    answer = Supervisor().aggregate(outputs, WorkflowType.RECOMMEND)
    return {"answer": answer}


def build_recommend_graph():
    builder = StateGraph(RecommendState)

    builder.add_node("profile_node", profile_node)
    builder.add_node("search_node", search_node)
    builder.add_node("reason_node", reason_node)
    builder.add_node("summary_node", summary_node)
    builder.add_node("cold_start_node", cold_start_node)
    builder.add_node("supervisor_node", supervisor_node)

    builder.add_edge(START, "profile_node")

    builder.add_conditional_edges(
        "profile_node",
        has_history_router,
        {
            "search_node": "search_node",
            "summary_node": "cold_start_node"
        }
    )

    builder.add_edge("search_node", "reason_node")
    builder.add_edge("reason_node", "summary_node")
    builder.add_edge("cold_start_node", "supervisor_node")
    builder.add_edge("summary_node", "supervisor_node")
    builder.add_edge("supervisor_node", END)

    return builder.compile()


recommend_graph = build_recommend_graph()


def run_recommend_workflow(user_id: str, question: str = None,
                           session_id: str = None,
                           top_k: int = 5) -> Dict[str, Any]:
    initial_state: RecommendState = {
        "user_id": user_id,
        "question": question,
        "session_id": session_id or "",
        "top_k": top_k,
        "user_profile": {},
        "candidate_videos": [],
        "recommended_videos": [],
        "reasons": [],
        "summary": "",
        "answer": "",
        "workflow_type": WorkflowType.RECOMMEND
    }

    result = recommend_graph.invoke(initial_state)

    return {
        "answer": result.get("answer", ""),
        "recommended_videos": result.get("recommended_videos", []),
        "reasons": result.get("reasons", []),
        "user_profile": result.get("user_profile", {}),
        "workflow_type": WorkflowType.RECOMMEND
    }


def resume_recommend_workflow(session_id: str) -> Dict[str, Any]:
    """从最近一次 checkpoint 恢复 recommend workflow"""
    mgr = CheckpointManager()
    last_cp = mgr.get_last_completed(session_id, WorkflowType.RECOMMEND)
    if not last_cp:
        return {"answer": "", "error": "无可用 checkpoint", "workflow_type": WorkflowType.RECOMMEND}

    completed_step = last_cp.step_name
    state = last_cp.state_snapshot

    if completed_step == "supervisor_node":
        return {
            "answer": state.get("answer", ""),
            "recommended_videos": state.get("recommended_videos", []),
            "reasons": state.get("reasons", []),
            "workflow_type": WorkflowType.RECOMMEND,
            "resumed_from": completed_step,
        }

    step_order = RECOMMEND_STEP_ORDER
    play_count = state.get("user_profile", {}).get("play_count", 0)
    if play_count <= 0:
        step_order = RECOMMEND_COLD_START_ORDER

    next_idx = step_order.index(completed_step) + 1 if completed_step in step_order else 0
    remaining_steps = step_order[next_idx:]

    step_fn_map = {
        "search_node": search_node,
        "reason_node": reason_node,
        "summary_node": summary_node,
        "cold_start_node": cold_start_node,
        "supervisor_node": supervisor_node,
    }

    for step_name in remaining_steps:
        step_fn = step_fn_map.get(step_name)
        if step_fn:
            try:
                step_result = step_fn(state)
                state.update(step_result)
            except Exception as e:
                _save_checkpoint(session_id, step_name, state, status="failed", error=str(e))
                return {"answer": state.get("answer", ""), "error": str(e),
                        "workflow_type": WorkflowType.RECOMMEND, "failed_at": step_name}

    return {
        "answer": state.get("answer", ""),
        "recommended_videos": state.get("recommended_videos", []),
        "reasons": state.get("reasons", []),
        "workflow_type": WorkflowType.RECOMMEND,
        "resumed_from": completed_step,
    }
