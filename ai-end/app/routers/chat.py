"""流式对话与 checkpoint 恢复。会话 CRUD 见 chat_sessions。"""
import logging
import uuid
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.agents.router import Router
from app.agents.workflows.chat_graph import resume_chat_workflow
from app.agents.workflows.constants import WorkflowType
from app.agents.workflows.recommend_workflow import resume_recommend_workflow
from app.agents.workflows.user_data_workflow import resume_user_data_workflow
from app.agents.workflows.video_qa_workflow import resume_video_qa_workflow
from app.conversation.context_manager import get_context_for_query
from app.conversation.intent_clarifier import IntentClarifier
from app.models import ChatRequest
from app.routers._shared import _json_dumps, require_auth
from app.routers.chat_pipeline import (
    extract_memories_from_conversation,
    parallel_agent_pipeline,
    record_streaming,
)
from app.tools import ChatTools
from app.tools.context_tools import build_context, save_message
from app.tools.memory_tools import MemoryTools
from app.tools.output_guard import FALLBACK_RESPONSE
from app.utils.security import validate_session_id

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest, http_request: Request, authed_user_id: str = Depends(require_auth)):
    client_disconnect_checker = None
    try:
        from app.utils.resilience import DisconnectChecker
        client_disconnect_checker = DisconnectChecker(
            is_disconnected=http_request.is_disconnected
        )
    except Exception:
        pass

    try:
        question = request.question
        video_id = request.videoId
        image_urls = request.imageUrls or []
        if request.sessionId and not validate_session_id(request.sessionId):
            session_id = str(uuid.uuid4())
        else:
            session_id = request.sessionId or str(uuid.uuid4())
        user_id = authed_user_id
        if request.userId and request.userId != authed_user_id:
            logger.warning(f"user_id 不匹配: 请求={request.userId}, token={authed_user_id}，已用 token 覆盖")
        logger.info(f"chat_stream: question={question}, video_id={video_id}, user_id={user_id}, session_id={session_id}")
        if not question:
            raise HTTPException(status_code=400, detail="问题不能为空")
        conversation_history: list = []
        if session_id:
            try:
                from app.agents.workflows import run_sync_in_executor as _rse
                ctx_messages = await _rse(build_context, session_id)
                pairs = []
                for m in ctx_messages:
                    if m.get("role") == "user":
                        pairs.append({"user": m["content"]})
                    elif m.get("role") == "assistant" and pairs:
                        pairs[-1]["assistant"] = m["content"]
                    elif m.get("role") == "system":
                        continue
                conversation_history = pairs
            except Exception as e:
                logger.warning(f"从Redis获取上下文失败: {e}")
                try:
                    from app.agents.workflows import run_sync_in_executor as _rse
                    records = await _rse(ChatTools.get_chat_history, user_id, session_id, 20)
                    pairs = []
                    for r in records:
                        if r.question and r.answer:
                            pairs.append({"user": r.question, "assistant": r.answer})
                    pairs.reverse()
                    conversation_history = pairs
                except Exception as e2:
                    logger.warning(f"从数据库获取历史失败: {e2}")
        memory_context = ""
        if user_id:
            try:
                from app.agents.workflows import run_sync_in_executor as _rse
                memories = await _rse(MemoryTools.recall_memories, user_id, question, 3)
                if memories:
                    memory_lines = [f"- (置信度{m.score:.1f}) {m.content}" for m in memories]
                    memory_context = "关于该用户，AI已知的信息：\n" + "\n".join(memory_lines)
                    logger.info(f"为用户 {user_id} 召回 {len(memories)} 条记忆")
            except Exception as e:
                logger.warning(f"记忆召回失败(不影响响应): {e}")
        if memory_context:
            conversation_history.insert(0, {"system_memory": memory_context})
        if image_urls:
            conversation_history.insert(0, {"system_memory": f"用户上传了 {len(image_urls)} 张图片，请结合图片内容回答。"})
        ctx = {}
        try:
            from app.agents.workflows import run_sync_in_executor as _rse
            ctx = await _rse(get_context_for_query, session_id, question)
            resolved_question = ctx["resolved_question"]
            referenced_video = ctx["referenced_video"]
            if ctx["resolved"]:
                logger.info(
                    f"指代消解: '{question}' → '{resolved_question}' "
                    f"({ctx['reference_type']}, video_id={referenced_video.get('video_id') if referenced_video else None})"
                )
                if referenced_video and not video_id:
                    video_id = referenced_video.get("video_id")
                question = resolved_question
        except Exception as e:
            logger.warning(f"指代消解失败(不影响响应): {e}")
        user_pref: dict = {}
        if user_id:
            try:
                from app.agents.workflows import run_sync_in_executor as _rse
                pref_mems = await _rse(MemoryTools.recall_memories, user_id, "", 20)
                tags = [m.content for m in pref_mems if m.type in ("preference", "activity")]
                if tags:
                    user_pref["favorite_tags"] = tags
            except Exception:
                pass
        from app.agents.workflows import run_sync_in_executor
        route_decision = await run_sync_in_executor(Router().hybrid_route_full, question, {"video_id": video_id})
        workflow_type = route_decision.workflow_type
        logger.info(f" Routed to: {workflow_type} (method={route_decision.method}, conf={route_decision.confidence:.2f})")
        try:
            clarifier = IntentClarifier()
            has_history = bool(ctx.get("last_recommendations"))
            mentioned = [w for w in question.split() if len(w) > 1]
            if clarifier.need_clarification(
                intent=workflow_type, user_id=user_id, user_preference=user_pref,
                video_id=video_id, mentioned_keywords=mentioned, question=question,
            ):
                clarification_text = clarifier.get_clarification(
                    intent=workflow_type, video_id=video_id,
                    mentioned_keywords=mentioned, has_history=has_history,
                )
                logger.info(f"智能追问: intent={workflow_type}, user={user_id[:8]}")

                async def clarification_stream():
                    yield f"data: {_json_dumps({'type': 'status', 'stage': 'clarifying', 'label': '需要更多信息'})}\n\n"
                    yield f"data: {_json_dumps({'type': 'text', 'content': clarification_text})}\n\n"
                    yield "data: [DONE]\n\n"
                return StreamingResponse(clarification_stream(), media_type="text/event-stream")
        except Exception as e:
            logger.warning(f"追问生成失败(不影响响应): {e}")

        async def generate():
            full_response = ""
            recommended_videos: List[Dict[str, Any]] = []
            recommended_reasons: List[str] = []
            winner_type_meta = ""
            try:
                async for event in parallel_agent_pipeline(
                    workflow_type, question, video_id, user_id, conversation_history,
                    image_urls, session_id, route_decision,
                ):
                    if client_disconnect_checker and await client_disconnect_checker.check():
                        logger.info(f"客户端已断开，提前结束 stream (session={session_id})")
                        try:
                            from app.utils.metrics import streaming_failures_total
                            streaming_failures_total.labels(
                                endpoint="chat_stream", failure_type="client_disconnect"
                            ).inc()
                        except Exception:
                            pass
                        break

                    event_type = event.get("type")
                    if event_type == "text":
                        full_response += event.get("content", "")
                    elif event_type == "meta":
                        meta = event.get("meta", {})
                        recommended_videos = meta.get("recommended_videos", []) or recommended_videos
                        winner_type_meta = meta.get("winner_type", "") or winner_type_meta
                    elif event_type == "videos":
                        if event.get("videos"):
                            recommended_videos = event["videos"]
                        if event.get("reasons"):
                            recommended_reasons = event["reasons"]
                    record_streaming(event)
                    yield f"data: {_json_dumps(event)}\n\n"
                has_data = bool(recommended_videos) or winner_type_meta in (
                    WorkflowType.RECOMMEND, WorkflowType.USER_DATA
                )
                if (not full_response or not full_response.strip()) and not has_data:
                    yield f"data: {_json_dumps({'type':'text','content':FALLBACK_RESPONSE})}\n\n"
                yield "data: [DONE]\n\n"
            except Exception as e:
                logger.error(f"Stream generation error: {e}", exc_info=True)
                yield f"data: {_json_dumps({'type':'text','content':FALLBACK_RESPONSE})}\n\n"
                yield "data: [DONE]\n\n"
            finally:
                from app.agents.workflows import run_sync_in_executor as _rse
                try:
                    if recommended_videos:
                        from app.conversation.context_manager import update_recommendations
                        await _rse(update_recommendations, session_id, recommended_videos)
                    if winner_type_meta == WorkflowType.VIDEO_QA and video_id:
                        from app.conversation.context_manager import update_video_qa
                        from app.tools import VideoTools
                        _video = await _rse(VideoTools.get_video_info, video_id)
                        _title = _video.videoName if _video else ""
                        _author = _video.nickName if _video else ""
                        await _rse(update_video_qa, session_id, {"video_id": video_id, "title": _title, "author": _author})
                except Exception as e:
                    logger.warning(f"写入指代上下文失败(不影响响应): {e}")
                has_anything = bool(full_response and full_response.strip()) or bool(recommended_videos)
                if has_anything:
                    try:
                        from app.agents.workflows import run_sync_in_executor as _rse
                        await _rse(save_message, session_id, "user", question)
                        await _rse(save_message, session_id, "assistant", full_response)
                        from app.tools.context_tools import async_summarize_context
                        await async_summarize_context(session_id)
                    except Exception as e:
                        logger.warning(f"保存上下文失败(不影响响应): {e}")
                    if user_id:
                        await _rse(
                            ChatTools.save_chat_history,
                            user_id, question, full_response,
                            session_id, image_urls or None,
                            videos=recommended_videos or None,
                            reasons=recommended_reasons or None,
                        )
                        if full_response and full_response.strip():
                            try:
                                from app.agents.workflows import run_sync_in_executor
                                await run_sync_in_executor(
                                    extract_memories_from_conversation, user_id, question, full_response, session_id,
                                )
                            except Exception as e:
                                logger.warning(f"记忆提取失败(不影响响应): {e}")

        return StreamingResponse(generate(), media_type="text/event-stream")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"chat stream error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="聊天失败") from e


def _find_resumable_checkpoint(session_id: str) -> Dict[str, Any]:
    from app.harness.checkpoint import CheckpointManager
    mgr = CheckpointManager()
    steps = mgr.list_steps(session_id, None)
    if not steps:
        for wf_type in WorkflowType.all():
            steps = mgr.list_steps(session_id, wf_type)
            if steps:
                break
    last_cp = None
    for wf_type in WorkflowType.all():
        last_cp = mgr.get_last_completed(session_id, wf_type)
        if last_cp:
            break
    completed_steps = mgr.list_steps(session_id, last_cp.workflow_type) if last_cp else []
    return {"steps": steps, "last_checkpoint": last_cp, "completed_steps": completed_steps}


@router.post("/chat/resume")
async def resume_workflow(request: Request, authed_user_id: str = Depends(require_auth)):
    try:
        body = await request.json()
        session_id = body.get("session_id")
        if not session_id:
            raise HTTPException(status_code=400, detail="session_id 不能为空")
        from app.agents.workflows import run_sync_in_executor
        owner_check = await run_sync_in_executor(ChatTools.get_chat_history, authed_user_id, session_id, 1)
        if not owner_check:
            logger.warning(f"resume 越权拦截: user={authed_user_id} 试图恢复 session={session_id}")
            raise HTTPException(status_code=404, detail="会话不存在")
        ckpt = await run_sync_in_executor(_find_resumable_checkpoint, session_id)
        steps = ckpt["steps"]
        last_cp = ckpt["last_checkpoint"]
        if not steps:
            raise HTTPException(status_code=404, detail="该 session 无 checkpoint 记录")
        if not last_cp:
            raise HTTPException(status_code=404, detail="无已完成的 checkpoint")
        wf_type = last_cp.workflow_type
        resume_fn_map = {
            WorkflowType.CHAT: resume_chat_workflow,
            WorkflowType.VIDEO_QA: resume_video_qa_workflow,
            WorkflowType.RECOMMEND: resume_recommend_workflow,
            WorkflowType.USER_DATA: resume_user_data_workflow,
        }
        resume_fn = resume_fn_map.get(wf_type)
        if not resume_fn:
            raise HTTPException(status_code=400, detail=f"不支持的 workflow 类型: {wf_type}")
        result = await run_sync_in_executor(resume_fn, session_id)
        return {
            "success": True,
            "workflow_type": wf_type,
            "resumed_from": result.get("resumed_from", "unknown"),
            "answer": result.get("answer", ""),
            "error": result.get("error"),
            "failed_at": result.get("failed_at"),
            "completed_steps": ckpt["completed_steps"],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"resume workflow error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="断点恢复失败") from e
