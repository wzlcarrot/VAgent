"""聊天并行 pipeline：与 FastAPI 路由解耦，便于单测。"""
import asyncio
import logging
import re
from typing import Any, Dict, List

from app.agents.supervisor import Supervisor
from app.agents.workflows.chat_graph import run_chat_workflow
from app.agents.workflows.constants import WorkflowType
from app.agents.workflows.recommend_workflow import run_recommend_workflow
from app.agents.workflows.user_data_workflow import run_user_data_workflow
from app.agents.workflows.video_qa_workflow import run_video_qa_workflow
from app.config import settings
from app.tools.memory_tools import MemoryTools
from app.tools.output_guard import ALL_AGENTS_FAILED_MSG, FALLBACK_RESPONSE
from app.utils.task_cancel import WorkflowCancelled

logger = logging.getLogger(__name__)

_CHINESE_NUM = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "几": 3}

WORKFLOW_TIMEOUT = 120.0


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


def extract_memories_from_conversation(user_id: str, question: str, answer: str, session_id: str = ""):
    if not user_id or not answer:
        return
    from typing import Literal

    from pydantic import BaseModel

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
        result = LLM_tools.chat_sync_typed(
            messages, MemoryExtractionResult, temperature=0.1, max_tokens=500,
            max_validation_retries=1, provider=settings.llm_provider,
        )
        if result is None:
            return
        for item in result.items:
            MemoryTools.save_memory(user_id=user_id, type=item.type, content=item.content, source="inferred", score=0.6)
    except WorkflowCancelled:
        raise
    except Exception as e:
        logger.warning(f"记忆提取异常: {e}")


async def run_workflow_to_result(
    wf_type: str, question: str, video_id: str = None,
    user_id: str = None, conversation_history: list = None,
    session_id: str = None, recommend_count: int = 5,
    route_decision: Any = None,
) -> dict:
    try:
        record_workflow_request(wf_type)
        from app.agents.workflows import run_sync_in_executor
        route_conf = float(route_decision.confidence) if route_decision is not None else 0.0
        is_winner = route_decision is not None and wf_type == route_decision.workflow_type
        conf = route_conf if is_winner else 0.5
        if wf_type == WorkflowType.VIDEO_QA:
            if not video_id:
                return {"workflow_type": wf_type, "answer": "", "confidence": 0.0, "recommended_videos": [], "reasons": []}
            result = await run_sync_in_executor(
                run_video_qa_workflow, question, video_id, user_id, session_id, timeout=WORKFLOW_TIMEOUT,
            )
            return {"workflow_type": wf_type, "answer": result.get("answer", ""), "confidence": conf, "recommended_videos": [], "reasons": []}
        if wf_type == WorkflowType.RECOMMEND:
            if not user_id:
                return {"workflow_type": wf_type, "answer": "", "confidence": 0.0, "recommended_videos": [], "reasons": []}
            result = await run_sync_in_executor(
                run_recommend_workflow, user_id, question, session_id, recommend_count, timeout=WORKFLOW_TIMEOUT,
            )
            return {
                "workflow_type": wf_type, "answer": result.get("answer", ""), "confidence": conf,
                "recommended_videos": result.get("recommended_videos", []), "reasons": result.get("reasons", []),
            }
        if wf_type == WorkflowType.USER_DATA:
            if not user_id:
                return {"workflow_type": wf_type, "answer": "", "confidence": 0.0, "recommended_videos": [], "reasons": []}
            result = await run_sync_in_executor(
                run_user_data_workflow, question, user_id, session_id, timeout=WORKFLOW_TIMEOUT,
            )
            return {"workflow_type": wf_type, "answer": result.get("answer", ""), "confidence": conf, "recommended_videos": [], "reasons": []}
        result = await run_sync_in_executor(
            run_chat_workflow, question, conversation_history or [], session_id, True, timeout=WORKFLOW_TIMEOUT,
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
):
    if route_decision is not None:
        yield {
            "type": "meta",
            "meta": {
                "winner_type": workflow_type,
                "confidence": route_decision.confidence,
                "method": route_decision.method,
            },
        }
    yield {"type": "status", "stage": "routing", "label": "分析意图"}
    eligible = [workflow_type]
    if workflow_type != WorkflowType.CHAT:
        eligible.append(WorkflowType.CHAT)
    yield {"type": "status", "stage": "parallel", "label": "主流程与兜底并行执行"}
    recommend_count = parse_recommend_count(question)
    tasks = [
        run_workflow_to_result(
            wf, question, video_id, user_id, conversation_history, session_id, recommend_count, route_decision,
        )
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

    final_method = route_decision.method if route_decision is not None else "unknown"
    if route_decision is not None and winner_type != route_decision.workflow_type:
        final_method = "fallback_priority"
    yield {
        "type": "meta",
        "meta": {
            "winner_type": winner_type,
            "confidence": winner_conf,
            "method": final_method,
        },
    }

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
    winner_text = re.sub(r"<think>.*?</think>\s*", "", winner_text, flags=re.DOTALL).strip()
    from app.agents.workflows.chat_graph import _sanitize_platform
    winner_text = _sanitize_platform(winner_text)
    if not winner_text or not winner_text.strip():
        yield {"type": "text", "content": FALLBACK_RESPONSE}
        yield {"type": "status", "stage": "done", "label": "完成"}
        return
    yield {"type": "status", "stage": "generating", "label": "生成回答"}
    if winner_type == WorkflowType.CHAT:
        chat_result = next((r for r in results if r["workflow_type"] == WorkflowType.CHAT), None)
        if image_urls:
            from app.tools.llm_tools import LLM_tools as LT
            vision_messages = [
                {"role": "system", "content": "你是一个能看懂图片的 AI 助手。根据用户的问题和图片内容，给出简洁有用的回答。"},
                {"role": "user", "content": f"用户问题：{question}\n\n参考信息：{winner_text}"},
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
        yield {"type": "text", "content": winner_text}
    yield {"type": "status", "stage": "done", "label": "完成"}
