from typing import Any, Dict, List, Tuple

from app.agents.workflows.constants import WorkflowType
from app.tools.output_guard import FALLBACK_RESPONSE


class Supervisor:
    """
    多Agent结果仲裁器：接收并行执行的工作流结果，按优先级和置信度仲裁最终回答。

    仲裁策略：
    1. 每个工作流返回 结果文本 + 置信度(0~1)
    2. 优先级最高的非空结果胜出（video_qa > user_data > recommend > chat）
    3. 同优先级时，置信度高的胜出
    4. 如果高优先级结果不可用（空/错误），降级到低优先级
    """

    WORKFLOW_PRIORITY: Dict[str, int] = {
        WorkflowType.VIDEO_QA: 4,
        WorkflowType.USER_DATA: 3,
        WorkflowType.RECOMMEND: 2,
        WorkflowType.CHAT: 1,
    }

    def format_result(self, agent_outputs: Dict[str, Any], workflow_type: str) -> str:
        """格式化单个工作流的输出"""
        return self._format_single(agent_outputs, workflow_type)

    aggregate = format_result

    def arbitrate(self, results: List[Tuple[str, str, float]]) -> Tuple[str, str, float]:
        """
        仲裁多个工作流的结果。

        Args:
            results: [(workflow_type, answer_text, confidence), ...]

        Returns:
            (winning_workflow, final_answer, effective_confidence)
        """
        if not results:
            return (WorkflowType.CHAT, FALLBACK_RESPONSE, 0.0)

        scored: List[Tuple[str, str, float, int, bool]] = []
        for wf, answer, conf in results:
            priority: int = self.WORKFLOW_PRIORITY.get(wf, 0)
            is_valid: bool = bool(answer) and not self._is_error(answer) and answer != FALLBACK_RESPONSE
            scored.append((wf, answer, conf, priority, is_valid))

        # 按 (优先级降序, 置信度降序) 排序
        scored.sort(key=lambda x: (x[3], x[2]), reverse=True)

        # 最高优先级有有效结果的胜出
        for wf, answer, conf, _, is_valid in scored:
            if is_valid:
                return (wf, answer, conf)

        # 全空时拿优先级最高的，但用 fallback 消息（避免返回错误文本）
        best: Tuple[str, str, float, int, bool] = scored[0]
        return (best[0], FALLBACK_RESPONSE, best[2])

    def _is_error(self, text: str) -> bool:
        """判断文本是否为错误信息"""
        if not text:
            return True
        stripped: str = text.strip()
        if stripped.startswith("[ERROR]") or stripped.startswith("[ERR]"):
            return True
        if stripped.startswith("Error:") or stripped.startswith("Exception:"):
            return True
        error_signatures: List[str] = [
            "Traceback (most recent call last):",
            "Internal Server Error",
            "HTTP 500",
            "java.lang.NullPointerException",
            "psycopg2.OperationalError",
            "psycopg2.InterfaceError",
        ]
        if any(sig in text for sig in error_signatures):
            return True
        # 通用错误关键词（含中文错误标识）
        lowered = text.lower()
        if any(kw in lowered for kw in ["error", "exception", "failed", "失败", "错误", "异常", "err:"]):
            return True
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                import json
                obj = json.loads(stripped)
                if isinstance(obj, dict) and "error" in obj:
                    return True
                return False
            except (json.JSONDecodeError, ValueError):
                pass
        return False

    def _format_single(self, outputs: Dict[str, Any], workflow_type: str) -> str:
        """根据 workflow 类型格式化输出"""
        if workflow_type == WorkflowType.VIDEO_QA:
            return self._aggregate_video_qa(outputs)
        elif workflow_type == WorkflowType.RECOMMEND:
            return self._aggregate_recommend(outputs)
        elif workflow_type == WorkflowType.CHAT:
            return self._aggregate_chat(outputs)
        elif workflow_type == WorkflowType.USER_DATA:
            return self._aggregate_user_data(outputs)
        else:
            return self._aggregate_default(outputs)

    def _aggregate_video_qa(self, outputs: Dict[str, Any]) -> str:
        """聚合视频问答结果"""
        video_info: Dict[str, Any] = outputs.get("video_info", {})
        knowledge: List[Dict[str, Any]] = outputs.get("knowledge", [])
        summary: str = outputs.get("summary", "")

        if summary:
            return summary

        parts: List[str] = []
        if video_info.get("title"):
            parts.append(f"视频标题：{video_info['title']}")
        if video_info.get("author"):
            parts.append(f"作者：{video_info['author']}")
        if video_info.get("duration"):
            parts.append(f"时长：{video_info['duration']}分钟")
        if video_info.get("tags"):
            parts.append(f"标签：{video_info['tags']}")

        result: str = "，".join(parts) if parts else ""

        if knowledge:
            result += "\n\n相关知识："
            for k in knowledge[:3]:
                if isinstance(k, dict) and k.get("content"):
                    result += f"\n- {k['content']}"

        return result if result else FALLBACK_RESPONSE

    def _aggregate_recommend(self, outputs: Dict[str, Any]) -> str:
        """聚合推荐结果。

        workflow 的 summary 已是完整 Markdown（标题/封面/关键词/作者/时间/播放量/理由），
        直接返回；仅当无 summary 时降级为旧的开场白+标题列表。
        """
        summary: str = outputs.get("summary", "") or outputs.get("answer", "")
        if summary and summary != FALLBACK_RESPONSE:
            return summary

        videos: List[Dict[str, Any]] = outputs.get("recommended_videos", [])
        reasons: List[str] = outputs.get("reasons", [])

        if not videos:
            return FALLBACK_RESPONSE

        count = min(len(videos), 5)
        result = f"为你找到 {count} 个相关视频：\n\n"

        for i, video in enumerate(videos[:5]):
            if not isinstance(video, dict):
                continue
            video_name: str = video.get("videoName", video.get("video_name", video.get("title", "未知视频")))
            reason: str = reasons[i] if i < len(reasons) else ""
            result += f"**{i+1}. {video_name}**"
            if reason:
                result += f"\n  {reason}"
            result += "\n\n"

        return result.strip()

    def _aggregate_chat(self, outputs: Dict[str, Any]) -> str:
        """聚合对话结果"""
        faq_content: List[str] = outputs.get("faq_content", [])
        guide_content: List[str] = outputs.get("guide_content", [])
        response: str = outputs.get("response", "")

        if response:
            return response

        parts: List[str] = []
        if faq_content:
            parts.append("常见问题：\n" + "\n".join(f"- {f}" for f in faq_content[:3]))
        if guide_content:
            if parts:
                parts.append("\n")
            parts.append("操作指南：\n" + "\n".join(f"- {g}" for g in guide_content[:3]))

        return "\n".join(parts) if parts else FALLBACK_RESPONSE

    def _aggregate_user_data(self, outputs: Dict[str, Any]) -> str:
        """聚合用户数据结果"""
        response: str = outputs.get("response", "")
        query_result: Dict[str, Any] = outputs.get("query_result", {})

        error_msg: str = query_result.get("error", "")
        if error_msg:
            return f"抱歉，无法查询：{error_msg}"

        if response:
            return response

        summary_text: str = query_result.get("summary_text", "")
        if summary_text:
            return summary_text

        return FALLBACK_RESPONSE

    def _aggregate_default(self, outputs: Dict[str, Any]) -> str:
        """默认聚合逻辑"""
        for key in ["response", "answer", "summary", "result"]:
            if key in outputs and outputs[key]:
                return outputs[key]
        return FALLBACK_RESPONSE
