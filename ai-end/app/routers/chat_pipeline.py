"""聊天并行 pipeline：与 FastAPI 路由解耦，便于单测。"""
import asyncio
import json
import logging
import queue
import re
from typing import Any, Dict, List

from app.agents.supervisor import Supervisor
from app.agents.workflows.chat_graph import run_chat_workflow
from app.agents.workflows.constants import WorkflowType
from app.agents.workflows.recommend_workflow import run_recommend_workflow
from app.agents.workflows.user_data_workflow import run_user_data_workflow
from app.agents.workflows.video_qa_workflow import run_video_qa_workflow
from app.config import settings
from app.streaming.event_bridge import citations_event, meta_event, status_event, text_event, videos_event
from app.tools.memory_tools import MemoryTools
from app.tools.output_guard import ALL_AGENTS_FAILED_MSG, FALLBACK_RESPONSE
from app.utils.task_cancel import WorkflowCancelled

logger = logging.getLogger(__name__)

_CHINESE_NUM = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "几": 3, "十": 5}

WORKFLOW_TIMEOUT = 120.0


def _harness_sse(event_type: str, **payload: Any) -> Dict[str, Any]:
    """构造 harness 调试 SSE 事件。"""
    from app.config import settings
    if not settings.harness_sse_enabled:
        return {}
    return {"type": "harness", "event": event_type, "payload": payload}


def _trace_and_sse(event_type: str, **payload: Any):
    try:
        from app.harness.run_trace import trace_event
        trace_event(event_type, **payload)
    except Exception:
        pass
    return _harness_sse(event_type, **payload)


def parse_recommend_count(text: str) -> int:
    """从「推荐两个视频」中提取数字，默认 5，上限 5。"""
    m = re.search(r"(\d+|" + "|".join(_CHINESE_NUM) + r")\s*(个|条)", text)
    if not m:
        return 5
    num_str = m.group(1)
    if num_str.isdigit():
        return max(1, min(int(num_str), 5))
    return _CHINESE_NUM.get(num_str, 5)


def record_streaming(event: Dict[str, Any]) -> None:
    try:
        import json as _j

        from app.utils.metrics import streaming_bytes_total, streaming_chunks_total
        chunk_str = _j.dumps(event, ensure_ascii=False)
        streaming_chunks_total.labels(endpoint="chat_stream").inc()
        streaming_bytes_total.labels(endpoint="chat_stream").inc(len(chunk_str))
    except Exception:
        pass


def record_workflow_request(wf_type: str) -> None:
    try:
        from app.utils.metrics import (
            chat_streaming_requests_total,
            recommendation_requests_total,
            user_data_requests_total,
            video_qa_requests_total,
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


def _memory_pending_key(user_id: str, session_id: str) -> str:
    return f"vagent:mem_pending:{session_id or user_id}"

# 原子攒批出队：够 min_turns 轮才取走全部（LRANGE+DEL 原子化）。
# 非原子的 lrange→delete 竞态会：并发 rpush 的新轮被 delete 误删（丢记忆提取）、
# 双请求同时 drain 重复提取（双倍 LLM 调用）。
_DRAIN_PENDING_LUA = """
local n = redis.call('LLEN', KEYS[1])
if n < tonumber(ARGV[1]) then
  return nil
end
local items = redis.call('LRANGE', KEYS[1], 0, -1)
redis.call('DEL', KEYS[1])
return items
"""


def maybe_extract_memories_from_conversation(user_id: str, question: str, answer: str,
                                             session_id: str = "") -> None:
    """批量攒够 `memory_extract_min_turns` 轮再提取一次（借鉴 ragent 的 pending 阈值）。

    好处：一轮闲聊往往没有可记信息，逐轮提取是浪费；攒批后把 LLM 调用从
    「轮数 × 1」降到「轮数 / 阈值」，且不丢信息（批量提取，不是丢弃）。
    Redis 不可用或阈值为 1 时，退化为逐轮提取。
    """
    if not user_id or not answer:
        return
    min_turns = max(1, int(settings.memory_extract_min_turns))
    if min_turns <= 1:
        extract_memories_from_conversation(user_id, question, answer, session_id)
        return

    try:
        from app.tools.context_tools import _get_redis

        r = _get_redis()
        if r is None:
            raise RuntimeError("redis unavailable")
        key = _memory_pending_key(user_id, session_id)
        r.rpush(key, json.dumps({"q": question, "a": answer}, ensure_ascii=False))
        r.expire(key, 3600)
        try:
            raw = r.eval(_DRAIN_PENDING_LUA, 1, key, min_turns)
        except Exception:
            # Lua 不可用时退回非原子读清（与旧行为一致），不影响功能
            if r.llen(key) < min_turns:
                return
            raw = r.lrange(key, 0, -1)
            r.delete(key)
        if not raw:
            return
        turns = []
        for item in raw or []:
            try:
                turns.append(json.loads(item))
            except (TypeError, json.JSONDecodeError):
                continue
        if turns:
            extract_memories_from_turns(user_id, turns, session_id)
    except Exception as e:
        logger.debug(f"记忆攒批失败，退化为逐轮提取: {e}")
        extract_memories_from_conversation(user_id, question, answer, session_id)


def extract_memories_from_conversation(user_id: str, question: str, answer: str, session_id: str = ""):
    """单轮提取（保留兼容）；批量路径见 `maybe_extract_memories_from_conversation`。"""
    extract_memories_from_turns(user_id, [{"q": question, "a": answer}], session_id)


def extract_memories_from_turns(user_id: str, turns: List[Dict[str, str]], session_id: str = ""):
    turns = [t for t in (turns or []) if t and (t.get("a") or "").strip()]
    if not user_id or not turns:
        return
    from typing import Literal

    from pydantic import BaseModel

    from app.tools.llm_tools import LLM_tools

    class ExtractedMemory(BaseModel):
        type: Literal["preference", "activity", "fact"]
        content: str

    class MemoryExtractionResult(BaseModel):
        items: List[ExtractedMemory]

    conversation_text = "\n".join(
        f"用户: {t.get('q', '')}\nAI: {t.get('a', '')}" for t in turns if t
    )
    if not conversation_text.strip():
        return

    messages = [
        {"role": "system", "content": "你是记忆提取器。从对话中提取关于用户的偏好、兴趣、事实信息。返回 JSON: {\"items\": [{\"type\": \"preference|activity|fact\", \"content\": \"...\"}]}如果没有值得记忆的信息，返回 {\"items\": []}。"},
        {"role": "user", "content": conversation_text},
    ]
    try:
        result = LLM_tools.chat_sync_typed(
            messages, MemoryExtractionResult, temperature=0.1, max_tokens=500,
            max_validation_retries=1, provider=settings.llm_provider,
        )
        if result is None:
            return

        # 写入前用 LLM Judge 判冲突（ADD / SUPERSEDE / NOOP），
        # 比 pg_trgm/embedding 相似度更能处理同义改写与否定（借鉴 ragent）。
        existing_dicts: List[dict] = []
        if settings.memory_judge_enabled:
            try:
                existing = MemoryTools.recall_memories(user_id, query="", top_k=20)
                existing_dicts = [
                    {"id": m.id, "type": m.type, "content": m.content} for m in existing
                ]
            except Exception as e:
                logger.debug(f"加载已有记忆失败（Judge 退化）: {e}")

        from app.agents.memory_judge import judge_memory

        for item in result.items:
            if settings.memory_judge_enabled:
                decision = judge_memory(item.content, existing_dicts, memory_type=item.type)
                if decision.action == "NOOP":
                    continue
                MemoryTools.save_memory(
                    user_id=user_id, type=item.type, content=item.content,
                    source="inferred", score=0.6,
                    supersede_id=decision.target_id if decision.action == "SUPERSEDE" else None,
                    supersede=(decision.action != "ADD"),
                )
            else:
                MemoryTools.save_memory(
                    user_id=user_id, type=item.type, content=item.content,
                    source="inferred", score=0.6,
                )

        # 记忆合并（二次压缩）：活跃过多时把一批低分记忆交给 LLM 合并，而非直接淘汰
        if settings.memory_consolidate_enabled:
            try:
                if MemoryTools.active_memory_count(user_id) > settings.memory_consolidate_trigger:
                    MemoryTools.consolidate_user_memories(user_id)
            except Exception as e:
                logger.debug(f"记忆合并失败（不影响写入）: {e}")
    except WorkflowCancelled:
        raise
    except Exception as e:
        logger.warning(f"记忆提取异常: {e}")


async def run_workflow_to_result(
    wf_type: str, question: str, video_id: str = None,
    user_id: str = None, conversation_history: list = None,
    session_id: str = None, recommend_count: int = 5,
    route_decision: Any = None,
    cancel_event=None,
) -> dict:
    try:
        record_workflow_request(wf_type)
        from app.agents.workflows import run_sync_in_executor
        route_conf = float(route_decision.confidence) if route_decision is not None else 0.0
        is_winner = route_decision is not None and wf_type == route_decision.workflow_type
        conf = route_conf if is_winner else 0.5
        if wf_type == WorkflowType.VIDEO_QA:
            if not video_id:
                return {
                    "workflow_type": wf_type, "answer": "", "confidence": 0.0,
                    "recommended_videos": [], "reasons": [], "citations": [],
                }
            result = await run_sync_in_executor(
                run_video_qa_workflow, question, video_id, user_id, session_id,
                conversation_history=conversation_history or [],
                timeout=WORKFLOW_TIMEOUT, cancel_event=cancel_event,
            )
            return {
                "workflow_type": wf_type,
                "answer": result.get("answer", ""),
                "confidence": conf,
                "recommended_videos": [],
                "reasons": [],
                "video_info": result.get("video_info", {}),
                "knowledge": result.get("knowledge", []),
                "citations": result.get("citations") or [],
                "corrective_applied": bool(result.get("corrective_applied")),
                "critic_applied": bool(result.get("critic_applied")),
            }
        if wf_type == WorkflowType.RECOMMEND:
            if not user_id:
                return {"workflow_type": wf_type, "answer": "", "confidence": 0.0, "recommended_videos": [], "reasons": []}
            result = await run_sync_in_executor(
                run_recommend_workflow, user_id, question, session_id, recommend_count,
                timeout=WORKFLOW_TIMEOUT, cancel_event=cancel_event,
            )
            return {
                "workflow_type": wf_type, "answer": result.get("answer", ""), "confidence": conf,
                "recommended_videos": result.get("recommended_videos", []), "reasons": result.get("reasons", []),
            }
        if wf_type == WorkflowType.USER_DATA:
            if not user_id:
                return {"workflow_type": wf_type, "answer": "", "confidence": 0.0, "recommended_videos": [], "reasons": []}
            result = await run_sync_in_executor(
                run_user_data_workflow, question, user_id, session_id,
                timeout=WORKFLOW_TIMEOUT, cancel_event=cancel_event,
            )
            return {"workflow_type": wf_type, "answer": result.get("answer", ""), "confidence": conf, "recommended_videos": [], "reasons": []}
        result = await run_sync_in_executor(
            run_chat_workflow, question, conversation_history or [], session_id, True,
            timeout=WORKFLOW_TIMEOUT, cancel_event=cancel_event,
        )
        return {
            "workflow_type": WorkflowType.CHAT, "answer": result.get("answer", ""), "confidence": conf,
            "recommended_videos": [], "reasons": [], "llm_messages": result.get("llm_messages"),
        }
    except asyncio.TimeoutError:
        logger.error(f"workflow {wf_type} 执行超时（>{WORKFLOW_TIMEOUT}s），已发出协作取消")
        return {"workflow_type": wf_type, "answer": "", "confidence": 0.0, "recommended_videos": [], "reasons": []}
    except WorkflowCancelled:
        logger.info(f"workflow {wf_type} 协作取消")
        return {"workflow_type": wf_type, "answer": "", "confidence": 0.0, "recommended_videos": [], "reasons": []}
    except Exception as e:
        logger.error(f"并行workflow {wf_type} 执行失败: {e}")
        return {"workflow_type": wf_type, "answer": "", "confidence": 0.0, "recommended_videos": [], "reasons": []}


async def parallel_agent_pipeline(
    workflow_type: str, question: str, video_id: str = None,
    user_id: str = None, conversation_history: list = None,
    image_urls: list = None, session_id: str = None,
    route_decision: Any = None,
    cancel_event=None,
):
    if route_decision is not None:
        evt = _trace_and_sse(
            "route_decision",
            workflow=workflow_type,
            confidence=route_decision.confidence,
            method=route_decision.method,
        )
        if evt:
            yield evt
        yield meta_event(
            route_decision.workflow_type,
            route_decision.confidence,
            route_decision.method,
        )
    yield status_event("routing", "分析意图")
    eligible = [workflow_type]
    if workflow_type != WorkflowType.CHAT:
        eligible.append(WorkflowType.CHAT)
    evt = _trace_and_sse("workflow_dispatch", workflows=eligible)
    if evt:
        yield evt
    yield status_event("parallel", "主流程与兜底并行执行")
    recommend_count = parse_recommend_count(question)
    tasks = [
        run_workflow_to_result(
            wf, question, video_id, user_id, conversation_history, session_id, recommend_count, route_decision,
            cancel_event,
        )
        for wf in eligible
    ]

    from app.harness.llm_progress import reset_llm_progress_queue, set_llm_progress_queue
    from app.harness.tool_progress import reset_tool_progress_queue, set_tool_progress_queue

    progress_q: queue.Queue = queue.Queue()
    progress_token = set_tool_progress_queue(progress_q)
    llm_token = set_llm_progress_queue(progress_q)

    async def _gather_workflows():
        return await asyncio.gather(*tasks, return_exceptions=True)

    gather_task = asyncio.create_task(_gather_workflows())
    try:
        while not gather_task.done():
            if cancel_event is not None and cancel_event.is_set():
                gather_task.cancel()
                from app.utils.task_cancel import abort_running_io
                abort_running_io(cancel_event)
                yield status_event("done", "已取消")
                return
            while True:
                try:
                    tool_evt = progress_q.get_nowait()
                    if tool_evt:
                        yield tool_evt
                except queue.Empty:
                    break
            await asyncio.sleep(0.03)
        while True:
            try:
                tool_evt = progress_q.get_nowait()
                if tool_evt:
                    yield tool_evt
            except queue.Empty:
                break
        raw_results = gather_task.result()
    finally:
        reset_tool_progress_queue(progress_token)
        reset_llm_progress_queue(llm_token)

    results = [r for r in raw_results if isinstance(r, dict)]
    if not results:
        yield text_event(ALL_AGENTS_FAILED_MSG)
        yield status_event("done", "完成")
        return
    supervisor = Supervisor()
    results_tuples = [(r["workflow_type"], r["answer"], r["confidence"]) for r in results]
    winner_type, winner_text, winner_conf = supervisor.arbitrate(results_tuples)

    final_method = route_decision.method if route_decision is not None else "unknown"
    if route_decision is not None and winner_type != route_decision.workflow_type:
        final_method = "fallback_priority"
    evt = _trace_and_sse(
        "supervisor_arbitrate",
        winner=winner_type,
        confidence=winner_conf,
        method=final_method,
    )
    if evt:
        yield evt
    yield meta_event(winner_type, winner_conf, final_method)

    try:
        from app.harness.hooks import HookEvent, hooks_manager
        stop_ctx = hooks_manager.trigger(
            HookEvent.STOP,
            session_id=session_id or "",
            winner_type=winner_type,
            confidence=winner_conf,
            answer_preview=(winner_text or "")[:200],
        )
        if stop_ctx.get("stop_reason"):
            _trace_and_sse("stop_hook", stop_reason=stop_ctx.get("stop_reason"))
    except Exception:
        pass

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
        reformatted = supervisor.format_result(full_outputs, winner_type)
        if reformatted and reformatted != FALLBACK_RESPONSE:
            winner_text = reformatted
        # 结构化推荐视频：单独发 videos 事件，前端 VideoCard 直接消费
        # （而不是只靠 markdown 文本里嵌的标题）
        if winner_type == WorkflowType.RECOMMEND:
            rec_videos = winner_result.get("recommended_videos") or []
            rec_reasons = winner_result.get("reasons") or []
            if rec_videos:
                yield videos_event(rec_videos, rec_reasons)
        if winner_type == WorkflowType.VIDEO_QA:
            citations = winner_result.get("citations") or []
            from app.harness.guardrails import check_output_video_qa
            g = check_output_video_qa(winner_text, citations)
            try:
                from app.harness.run_trace import trace_event
                trace_event(
                    "guardrail",
                    stage="output_video_qa",
                    action=g.action,
                    reason=g.reason,
                )
            except Exception:
                pass
            if g.action == "rewrite" and g.rewritten:
                winner_text = g.rewritten
                citations = []
            if citations:
                from app.tools.video_qa_retrieval import strip_evidence_footer
                winner_text = strip_evidence_footer(winner_text)
                yield citations_event(citations)
    winner_text = re.sub(r"<think>.*?</think>\s*", "", winner_text, flags=re.DOTALL).strip()
    from app.agents.workflows.chat_graph import _sanitize_platform
    winner_text = _sanitize_platform(winner_text)
    if not winner_text or not winner_text.strip():
        yield text_event(FALLBACK_RESPONSE)
        yield status_event("done", "完成")
        return
    yield status_event("generating", "生成回答")
    if winner_type == WorkflowType.CHAT:
        chat_result = next((r for r in results if r["workflow_type"] == WorkflowType.CHAT), None)
        if image_urls:
            from app.tools.llm_tools import LLM_tools as LT
            vision_messages = [
                {"role": "system", "content": "你是一个能看懂图片的 AI 助手。根据用户的问题和图片内容，给出简洁有用的回答。"},
                {"role": "user", "content": f"用户问题：{question}\n\n参考信息：{winner_text}"},
            ]
            async for chunk in LT.stream_chat(vision_messages, image_urls=image_urls):
                yield text_event(chunk)
        elif chat_result and chat_result.get("llm_messages"):
            from app.tools.llm_tools import LLM_tools as LT
            async for chunk in LT.stream_chat(chat_result["llm_messages"]):
                yield text_event(chunk)
        else:
            yield text_event(winner_text)
    else:
        yield text_event(winner_text)
    yield status_event("done", "完成")
