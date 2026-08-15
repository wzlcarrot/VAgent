"""
聊天相关路由：sessions, history, search, delete, stream, resume, checkpoints
"""
import logging
import asyncio
import re
import time
import uuid
from typing import List, Dict, Any
from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import StreamingResponse
from app.models import ChatRequest
from app.agents.workflows.constants import WorkflowType
from app.agents.router import Router
from app.agents.supervisor import Supervisor
from app.agents.workflows.video_qa_workflow import run_video_qa_workflow, resume_video_qa_workflow
from app.agents.workflows.recommend_workflow import run_recommend_workflow, resume_recommend_workflow
from app.agents.workflows.chat_graph import run_chat_workflow, resume_chat_workflow
from app.agents.workflows.user_data_workflow import run_user_data_workflow, resume_user_data_workflow

_CHINESE_NUM = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "几": 3}  # "几"→默认按 3 个理解


def _parse_recommend_count(text: str) -> int:
    """从"推荐两个视频"中提取数字，默认返回 5"""
    m = re.search(r"(\d+|" + "|".join(_CHINESE_NUM) + r")\s*(个|条)", text)
    if not m:
        return 5
    num_str = m.group(1)
    if num_str.isdigit():
        return max(1, min(int(num_str), 5))
    return _CHINESE_NUM.get(num_str, 5)


from app.tools import ChatTools
from app.tools.db import get_global_pool
from app.routers._shared import require_auth, _json_dumps
from app.config import settings
from psycopg2.extras import RealDictCursor
from app.utils.security import validate_session_id
from app.tools.output_guard import FALLBACK_RESPONSE, ALL_AGENTS_FAILED_MSG
from app.tools.context_tools import build_context, save_message
from app.conversation.context_manager import get_context_for_query
from app.conversation.intent_clarifier import IntentClarifier
from app.tools.memory_tools import MemoryTools

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/chat/sessions")
async def get_chat_sessions(limit: int = 20, offset: int = 0, authed_user_id: str = Depends(require_auth)):
    try:
        limit = max(1, min(limit, 100))
        offset = max(0, offset)
        from app.agents.workflows import run_sync_in_executor
        sessions = await run_sync_in_executor(ChatTools.get_chat_sessions, authed_user_id, limit, offset)
        return {"sessions": sessions}
    except Exception as e:
        logger.error(f"获取会话列表失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="获取会话列表失败")


@router.get("/chat/history")
async def get_chat_history(session_id: str = None, limit: int = 50, authed_user_id: str = Depends(require_auth)):
    try:
        from app.agents.workflows import run_sync_in_executor
        records = await run_sync_in_executor(ChatTools.get_chat_history, authed_user_id, session_id, limit)
        import json as _json
        messages = []
        for r in records:
            # 解析 videos/reasons JSONB 字段
            videos_val = r.videos
            if isinstance(videos_val, str):
                try:
                    videos_val = _json.loads(videos_val)
                except Exception:
                    videos_val = None
            reasons_val = r.reasons
            if isinstance(reasons_val, str):
                try:
                    reasons_val = _json.loads(reasons_val)
                except Exception:
                    reasons_val = None
            if r.question:
                msg = {
                    "role": "user",
                    "content": r.question,
                    "timestamp": str(r.created_at) if r.created_at else "",
                    "session_id": r.session_id
                }
                if r.image_urls:
                    msg["image_urls"] = r.image_urls
                messages.append(msg)
            if r.answer or videos_val:
                msg = {
                    "role": "assistant",
                    "content": r.answer or "",
                    "timestamp": str(r.created_at) if r.created_at else "",
                    "session_id": r.session_id
                }
                if videos_val:
                    msg["videos"] = videos_val
                if reasons_val:
                    msg["reasons"] = reasons_val
                messages.append(msg)
        messages.sort(key=lambda m: m["timestamp"])
        return {"messages": messages}
    except Exception as e:
        logger.error(f"获取聊天历史失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="获取聊天历史失败")


@router.get("/chat/search")
async def search_chat_content(q: str = "", limit: int = 50, authed_user_id: str = Depends(require_auth)):
    try:
        from app.utils.security import escape_like_pattern, sanitize_search_input
        if not q:
            return {"results": []}
        q = sanitize_search_input(q)
        if not q:
            return {"results": []}
        from app.agents.workflows import run_sync_in_executor
        results = await run_sync_in_executor(_search_chat_db, authed_user_id, q, limit)
        return {"results": results}
    except Exception as e:
        logger.error(f"搜索聊天内容失败: {e}")
        return {"results": []}


def _search_chat_db(user_id: str, q: str, limit: int) -> List[Dict[str, Any]]:
    from app.utils.security import escape_like_pattern
    pool = get_global_pool()
    if pool is None:
        return []
    conn = pool.getconn()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        like_pattern = f"%{escape_like_pattern(q)}%"
        cursor.execute("""
            SELECT DISTINCT ch.session_id, ch.question, ch.answer, ch.created_at,
                   MIN(ch.created_at) OVER (PARTITION BY ch.session_id) as session_start
            FROM chat_history ch
            WHERE ch.user_id = %s
              AND (ch.question ILIKE %s OR ch.answer ILIKE %s)
            ORDER BY ch.created_at DESC
            LIMIT %s
        """, (user_id, like_pattern, like_pattern, limit))
        rows = cursor.fetchall()
        cursor.close()
        seen = set()
        results = []
        for r in rows:
            sid = r["session_id"]
            if sid in seen:
                continue
            seen.add(sid)
            snippet = r["answer"] or r["question"] or ""
            idx = snippet.lower().find(q.lower())
            if idx > 0:
                start = max(0, idx - 40)
                end = min(len(snippet), idx + len(q) + 60)
                snippet = ("..." if start > 0 else "") + snippet[start:end] + ("..." if end < len(snippet) else "")
            results.append({
                "session_id": sid,
                "title": (r["question"] or "")[:60],
                "snippet": snippet,
                "matched_in": "question" if q.lower() in (r["question"] or "").lower() else "answer",
                "created_at": str(r.get("created_at") or ""),
            })
        return results[:limit]
    finally:
        pool.putconn(conn)


@router.delete("/chat/session/{session_id}")
async def delete_chat_session(session_id: str, authed_user_id: str = Depends(require_auth)):
    try:
        from app.agents.workflows import run_sync_in_executor
        existing = await run_sync_in_executor(ChatTools.get_chat_history, authed_user_id, session_id, 1)
        if not existing:
            logger.warning(f"删除会话越权拦截: user={authed_user_id} 试图删除 session={session_id}")
            raise HTTPException(status_code=404, detail="会话不存在")
        success = await run_sync_in_executor(ChatTools.delete_chat_session, authed_user_id, session_id)
        return {"success": success}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除会话失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="删除会话失败")

@router.get("/chat/checkpoints")
async def get_checkpoints(session_id: str, authed_user_id: str = Depends(require_auth)):
    try:
        from app.agents.workflows import run_sync_in_executor
        owner_check = await run_sync_in_executor(ChatTools.get_chat_history, authed_user_id, session_id, 1)
        if not owner_check:
            logger.warning(f"checkpoints 越权拦截: user={authed_user_id} 试图查 session={session_id}")
            raise HTTPException(status_code=404, detail="会话不存在")
        from app.harness.checkpoint import CheckpointManager
        mgr = CheckpointManager()
        all_steps = []
        for wf_type in WorkflowType.all():
            steps = mgr.list_step_details(session_id, wf_type)
            if steps:
                last_cp = mgr.get_last_completed(session_id, wf_type)
                all_steps.append({
                    "workflow_type": wf_type,
                    "steps": steps,
                    "last_completed_step": last_cp.step_name if last_cp else None,
                    "last_completed_at": last_cp.created_at if last_cp else None,
                })
        return {"session_id": session_id, "checkpoints": all_steps}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取 checkpoint 失败: {e}")
        raise HTTPException(status_code=500, detail="获取 checkpoint 失败")


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest, http_request: Request, authed_user_id: str = Depends(require_auth)):
    # 关键：检测客户端是否提前 disconnect，避免流式输出浪费 LLM token
    client_disconnect_checker = None
    try:
        from app.utils.resilience import DisconnectChecker
        # FastAPI 提供的 is_disconnected 是同步方法
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
                logger.info(f"指代消解: '{question}' → '{resolved_question}' ({ctx['reference_type']}, video_id={referenced_video.get('video_id') if referenced_video else None})")
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
                tags = []
                for m in pref_mems:
                    if m.type in ("preference", "activity"):
                        tags.append(m.content)
                if tags:
                    user_pref["favorite_tags"] = tags
            except Exception:
                pass
        from app.agents.workflows import run_sync_in_executor
        workflow_type = await run_sync_in_executor(Router().hybrid_route, question, {"video_id": video_id})
        logger.info(f" Routed to: {workflow_type}")
        try:
            clarifier = IntentClarifier()
            has_history = bool(ctx.get("last_recommendations"))
            mentioned = [w for w in question.split() if len(w) > 1]
            if clarifier.need_clarification(intent=workflow_type, user_id=user_id, user_preference=user_pref, video_id=video_id, mentioned_keywords=mentioned):
                clarification_text = clarifier.get_clarification(intent=workflow_type, video_id=video_id, mentioned_keywords=mentioned, has_history=has_history)
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
                async for event in _parallel_agent_pipeline(workflow_type, question, video_id, user_id, conversation_history, image_urls, session_id):
                    # 客户端 disconnect 检测：提前中断 stream，避免浪费 LLM 资源
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
                        recommended_videos = meta.get("recommended_videos", []) or []
                        winner_type_meta = meta.get("winner_type", "")
                        # reasons 在 videos 事件里更准确（和 videoId 一一对应）
                        continue
                    elif event_type == "videos":
                        # 收集 reasons（和 videos 一起存 DB）
                        if event.get("reasons"):
                            recommended_reasons = event["reasons"]
                    _record_streaming(event, session_id)
                    yield f"data: {_json_dumps(event)}\n\n"
                # RECOMMEND/USER_DATA 有数据时（视频/记录），full_response 是空的也属正常
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
                try:
                    from app.agents.workflows import run_sync_in_executor as _rse
                    if recommended_videos:
                        from app.conversation.context_manager import update_recommendations
                        await _rse(update_recommendations, session_id, recommended_videos)
                    if winner_type_meta == "video_qa" and video_id:
                        from app.conversation.context_manager import update_video_qa
                        from app.tools import VideoTools
                        _video = await _rse(VideoTools.get_video_info, video_id)
                        _title = _video.videoName if _video else ""
                        _author = _video.nickName if _video else ""
                        await _rse(update_video_qa, session_id, {"video_id": video_id, "title": _title, "author": _author})
                except Exception as e:
                    logger.warning(f"写入指代上下文失败(不影响响应): {e}")
                # 即使 full_response 为空（仅 videos 事件），也要保存（否则刷新后丢失视频推荐）
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
                        # 把 recommended_videos + reasons 也存到 DB（videos/reasons JSONB 列）
                        ChatTools.save_chat_history(
                            user_id, question, full_response,
                            session_id, image_urls or None,
                            videos=recommended_videos or None,
                            reasons=recommended_reasons or None,
                        )
                        # 记忆提取只用真实回答文本（没有文本时跳过）
                        if full_response and full_response.strip():
                            try:
                                from app.agents.workflows import run_sync_in_executor
                                await run_sync_in_executor(_extract_memories_from_conversation, user_id, question, full_response, session_id)
                            except Exception as e:
                                logger.warning(f"记忆提取失败(不影响响应): {e}")

        return StreamingResponse(generate(), media_type="text/event-stream")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"chat stream error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="聊天失败")


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
        from app.harness.checkpoint import CheckpointManager
        mgr = CheckpointManager()
        steps = mgr.list_steps(session_id, None)
        if not steps:
            for wf_type in WorkflowType.all():
                steps = mgr.list_steps(session_id, wf_type)
                if steps:
                    break
        if not steps:
            raise HTTPException(status_code=404, detail="该 session 无 checkpoint 记录")
        last_cp = None
        for wf_type in WorkflowType.all():
            last_cp = mgr.get_last_completed(session_id, wf_type)
            if last_cp:
                break
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
        from app.agents.workflows import run_sync_in_executor
        result = await run_sync_in_executor(resume_fn, session_id)
        return {
            "success": True,
            "workflow_type": wf_type,
            "resumed_from": result.get("resumed_from", "unknown"),
            "answer": result.get("answer", ""),
            "error": result.get("error"),
            "failed_at": result.get("failed_at"),
            "completed_steps": mgr.list_steps(session_id, wf_type),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"resume workflow error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="断点恢复失败")


async def _parallel_agent_pipeline(workflow_type: str, question: str, video_id: str = None,
                                    user_id: str = None, conversation_history: list = None,
                                    image_urls: list = None, session_id: str = None):
    yield {"type": "status", "stage": "routing", "label": "分析意图"}
    eligible = [workflow_type]
    if workflow_type != WorkflowType.CHAT:
        eligible.append(WorkflowType.CHAT)
    yield {"type": "status", "stage": "parallel", "label": "多Agent并行分析"}
    # 解析用户问题中的推荐数量（"推荐两个视频"→ 2）
    recommend_count = _parse_recommend_count(question)
    tasks = [
        _run_workflow_to_result(wf, question, video_id, user_id, conversation_history, session_id, recommend_count)
        for wf in eligible
    ]
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)
    results = [r for r in raw_results if isinstance(r, dict)]
    if not results:
        yield {"type": "text", "content": ALL_AGENTS_FAILED_MSG}
        yield {"type": "status", "stage": "done", "label": "完成"}
        return
    supervisor = Supervisor()
    results_tuples = [(r["workflow_type"], r["answer"], r["confidence"]) for r in results]
    winner_type, winner_text, winner_conf = supervisor.arbitrate(results_tuples)

    # 重新生成 winner_text，传入完整 results（让 supervisor 能拿到 reasons/videos 生成推荐理由）
    winner_result = next((r for r in results if r["workflow_type"] == winner_type), None)
    if winner_result:
        full_outputs = {
            "user_profile": winner_result.get("user_profile", {}),
            "recommended_videos": winner_result.get("recommended_videos", []),
            "reasons": winner_result.get("reasons", []),
            "video_info": winner_result.get("video_info", {}),
            "knowledge": winner_result.get("knowledge", []),
            "summary": winner_result.get("answer", ""),
            "response": winner_result.get("answer", ""),
            "query_result": winner_result.get("query_result", {}),
        }
        # 重新格式化，让 _aggregate_recommend 拿到 reasons
        reformatted = supervisor.format_result(full_outputs, winner_type)
        if reformatted and reformatted != FALLBACK_RESPONSE:
            winner_text = reformatted
    # 统一过滤 MiniMax-M3 等推理模型的 <think>...</think> 块
    winner_text = re.sub(r"<think>.*?</think>\s*", "", winner_text, flags=re.DOTALL).strip()
    if not winner_text or not winner_text.strip():
        yield {"type": "text", "content": FALLBACK_RESPONSE}
        yield {"type": "status", "stage": "done", "label": "完成"}
        return
    yield {"type": "status", "stage": "generating", "label": "生成回答"}
    if winner_type == WorkflowType.CHAT:
        chat_result = None
        for r in results:
            if r["workflow_type"] == WorkflowType.CHAT:
                chat_result = r
                break
        if image_urls:
            from app.tools.llm_tools import LLM_tools as LT
            vision_messages = [
                {"role": "system", "content": "你是一个能看懂图片的 AI 助手。根据用户的问题和图片内容，给出简洁有用的回答。"},
                {"role": "user", "content": f"用户问题：{question}\n\n参考信息：{winner_text}"}
            ]
            async for chunk in LT.stream_chat(vision_messages, image_urls=image_urls):
                yield {"type": "text", "content": chunk}
        elif chat_result and chat_result.get("llm_messages"):
            from app.tools.llm_tools import LLM_tools as LT
            async for chunk in LT.stream_chat(chat_result["llm_messages"]):
                yield {"type": "text", "content": chunk}
        else:
            yield {"type": "text", "content": winner_text}
    else:
        # RECOMMEND/USER_DATA/VIDEO_QA winner：yield 文本（推荐已生成含全字段的 markdown）
        yield {"type": "text", "content": winner_text}
    yield {"type": "status", "stage": "done", "label": "完成"}


async def _run_workflow_to_result(wf_type: str, question: str, video_id: str = None,
                            user_id: str = None, conversation_history: list = None,
                            session_id: str = None, recommend_count: int = 5) -> dict:
    try:
        _record_workflow_request(wf_type)
        from app.agents.workflows import run_sync_in_executor
        # 单 workflow 超时保护：防止卡死的 LLM/DB 调用永久占用线程池线程
        WORKFLOW_TIMEOUT = 120.0
        if wf_type == WorkflowType.VIDEO_QA:
            if not video_id:
                return {"workflow_type": wf_type, "answer": "", "confidence": 0.0, "recommended_videos": [], "reasons": []}
            result = await run_sync_in_executor(run_video_qa_workflow, question, video_id, user_id, session_id, timeout=WORKFLOW_TIMEOUT)
            return {"workflow_type": wf_type, "answer": result.get("answer", ""), "confidence": 0.9, "recommended_videos": [], "reasons": []}
        if wf_type == WorkflowType.RECOMMEND:
            if not user_id:
                return {"workflow_type": wf_type, "answer": "", "confidence": 0.0, "recommended_videos": [], "reasons": []}
            result = await run_sync_in_executor(run_recommend_workflow, user_id, question, session_id, recommend_count, timeout=WORKFLOW_TIMEOUT)
            return {"workflow_type": wf_type, "answer": result.get("answer", ""), "confidence": 0.8, "recommended_videos": result.get("recommended_videos", []), "reasons": result.get("reasons", [])}
        if wf_type == WorkflowType.USER_DATA:
            if not user_id:
                return {"workflow_type": wf_type, "answer": "", "confidence": 0.0, "recommended_videos": [], "reasons": []}
            result = await run_sync_in_executor(run_user_data_workflow, question, user_id, session_id, timeout=WORKFLOW_TIMEOUT)
            return {"workflow_type": wf_type, "answer": result.get("answer", ""), "confidence": 0.85, "recommended_videos": [], "reasons": []}
        result = await run_sync_in_executor(run_chat_workflow, question, conversation_history or [], session_id, True, timeout=WORKFLOW_TIMEOUT)
        return {"workflow_type": WorkflowType.CHAT, "answer": result.get("answer", ""), "confidence": 0.7, "recommended_videos": [], "reasons": [], "llm_messages": result.get("llm_messages")}
    except asyncio.TimeoutError:
        logger.error(f"workflow {wf_type} 执行超时（>120s）")
        return {"workflow_type": wf_type, "answer": "", "confidence": 0.0, "recommended_videos": [], "reasons": []}
    except Exception as e:
        logger.error(f"并行workflow {wf_type} 执行失败: {e}")
        return {"workflow_type": wf_type, "answer": "", "confidence": 0.0, "recommended_videos": [], "reasons": []}


def _extract_memories_from_conversation(user_id: str, question: str, answer: str, session_id: str = ""):
    if not user_id or not answer:
        return
    from pydantic import BaseModel
    from typing import Literal, List
    from app.tools.llm_tools import LLM_tools
    class ExtractedMemory(BaseModel):
        type: Literal["preference", "activity", "fact"]
        content: str
    class MemoryExtractionResult(BaseModel):
        items: List[ExtractedMemory]
    messages = [
        {"role": "system", "content": "你是记忆提取器。从对话中提取关于用户的偏好、兴趣、事实信息。返回 JSON: {\"items\": [{\"type\": \"preference|activity|fact\", \"content\": \"...\"}]}如果没有值得记忆的信息，返回 {\"items\": []}。"},
        {"role": "user", "content": f"用户: {question}\nAI: {answer}"},
    ]
    try:
        result = LLM_tools.chat_sync_typed(messages, MemoryExtractionResult, temperature=0.1, max_tokens=500, max_validation_retries=1, provider=settings.llm_provider)
        if result is None:
            return
        for item in result.items:
            MemoryTools.save_memory(user_id=user_id, type=item.type, content=item.content, source="inferred", score=0.6)
    except Exception as e:
        logger.warning(f"记忆提取异常: {e}")


def _record_streaming(event: Dict[str, Any], session_id: str) -> None:
    """记录 SSE 流式 chunk/字节指标"""
    try:
        import json as _j
        from app.utils.metrics import streaming_chunks_total, streaming_bytes_total
        chunk_str = _j.dumps(event, ensure_ascii=False)
        streaming_chunks_total.labels(endpoint="chat_stream").inc()
        streaming_bytes_total.labels(endpoint="chat_stream").inc(len(chunk_str))
    except Exception:
        pass


def _record_workflow_request(wf_type: str) -> None:
    """按 workflow 类型记录业务请求计数"""
    try:
        from app.utils.metrics import (
            video_qa_requests_total, recommendation_requests_total,
            user_data_requests_total, chat_streaming_requests_total,
        )
        metric = {
            WorkflowType.VIDEO_QA: video_qa_requests_total,
            WorkflowType.RECOMMEND: recommendation_requests_total,
            WorkflowType.USER_DATA: user_data_requests_total,
            WorkflowType.CHAT: chat_streaming_requests_total,
        }.get(wf_type)
        if metric:
            metric.labels(result="dispatched").inc()
    except Exception:
        pass
