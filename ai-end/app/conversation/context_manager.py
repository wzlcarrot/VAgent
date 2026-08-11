"""
多轮对话上下文管理 + 指代消解

解决问题：
  用户：推荐一些科技视频
  AI：[推荐 5 个视频]
  用户：第二个视频讲了什么？
  旧 AI：❌ 不知道"第二个"是哪个
  新 AI：✅ 自动关联 last_recommendations[1]

设计：
- 每次推荐/视频问答结果存入 Redis（key: session_ref:{session_id}）
- TTL 跟随 context_ttl（默认 2h）
- 解析指代词前先尝试规则匹配（不调 LLM），匹配不到保持原 question
- 同时记录 mentioned_items 用于"刚才那个"类指代

Redis schema（session_ref:{session_id}）：
{
  "last_recommendations": [
    {"video_id": "v1", "title": "...", "author": "...", "tags": [...]},
    ...
  ],
  "last_video_qa": {"video_id": "v1", "title": "...", "author": "..."},
  "mentioned_items": [...],  # 最近 10 条对话中提到的实体
  "intent_chain": ["recommend", "video_qa"],  # 最近 10 个意图
  "updated_at": 1234567890.0
}

Redis 不可用时降级到内存 dict（单进程仍可用）。
"""
import json
import logging
import re
import threading
import time
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


# ─── 内存兜底（Redis 不可用时使用） ───
_memory_store: Dict[str, Dict[str, Any]] = {}
_memory_lock = threading.Lock()
_REDIS_PREFIX = "session_ref:"
_CONTEXT_KEY = "session_ref"

# ─── 指代词模式 ───
_ORDINAL_PATTERN = re.compile(
    r"第\s*([一二三四五六七八九十百千0-9]+)\s*(个|条|个视频|条视频|个那个)"
)
_PRONOUN_PATTERN = re.compile(
    r"(这个视频|那个视频|刚才那个|刚才那个视频|刚才的|上一个|下一个|这条|那条|这视频|那视频|这个|那个|此)"
)
_POS_PATTERN = re.compile(r"(第一个|第二个|第三个|第四个|第五个|最后一个|倒数第一个|倒数第二个)")


_ORDINAL_MAP = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}

_CHINESE_DIGITS = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9,
}
_CHINESE_SCALES = {"十": 10, "百": 100, "千": 1000}


def _parse_chinese_number(text: str) -> Optional[int]:
    """'二十一' → 21, '一百二十三' → 123"""
    if not text:
        return None
    total = 0
    current = 0
    for ch in text:
        if ch in _CHINESE_DIGITS:
            current = _CHINESE_DIGITS[ch]
        elif ch in _CHINESE_SCALES:
            scale = _CHINESE_SCALES[ch]
            total += (current or 1) * scale
            current = 0
        else:
            return None
    total += current
    return total


def _parse_ordinal(text: str) -> Optional[int]:
    """'一' → 1, '十二' → 12, '二十一' → 21, '21' → 21"""
    if text.isdigit():
        return int(text)
    if text in _ORDINAL_MAP:
        return _ORDINAL_MAP[text]
    return _parse_chinese_number(text)


def _get_redis():
    """惰性取 Redis 客户端"""
    try:
        from app.tools.context_tools import _get_redis
        return _get_redis()
    except Exception:
        return None


def _redis_key(session_id: str) -> str:
    return f"{_REDIS_PREFIX}{session_id}"


def _load_context(session_id: str) -> Dict[str, Any]:
    """从 Redis 或内存加载 session 上下文"""
    r = _get_redis()
    if r is not None:
        try:
            raw = r.get(_redis_key(session_id))
            if raw:
                return json.loads(raw)
        except Exception as e:
            logger.debug(f"读 Redis session_ref 失败: {e}")
    with _memory_lock:
        return dict(_memory_store.get(session_id, {
            "last_recommendations": [],
            "last_video_qa": {},
            "mentioned_items": [],
            "intent_chain": [],
            "updated_at": 0.0,
        }))


def _save_context(session_id: str, ctx: Dict[str, Any]) -> None:
    """持久化 session 上下文"""
    ctx["updated_at"] = time.time()
    r = _get_redis()
    if r is not None:
        try:
            from app.config import settings
            r.setex(_redis_key(session_id), settings.context_ttl, json.dumps(ctx, ensure_ascii=False, default=str))
            return
        except Exception as e:
            logger.debug(f"写 Redis session_ref 失败: {e}")
    with _memory_lock:
        _memory_store[session_id] = ctx


def update_recommendations(session_id: str, videos: List[Dict[str, Any]]) -> None:
    """
    AI 推荐完成后调用，记录推荐列表供下次追问。
    videos: [{"video_id": ..., "title": ..., "author": ..., "tags": [...]}, ...]
    """
    if not session_id or not videos:
        return
    ctx = _load_context(session_id)
    ctx["last_recommendations"] = videos[:10]  # 保留前 10
    mentioned = ctx.get("mentioned_items", [])
    for v in videos[:5]:
        mentioned.append({"type": "video", "id": v.get("video_id"), "title": v.get("title")})
    ctx["mentioned_items"] = mentioned[-20:]  # 最近 20 个
    chain = ctx.get("intent_chain", [])
    chain.append("recommend")
    ctx["intent_chain"] = chain[-10:]
    _save_context(session_id, ctx)


def update_video_qa(session_id: str, video_info: Dict[str, Any]) -> None:
    """视频问答完成后调用，记录当前视频上下文"""
    if not session_id or not video_info:
        return
    ctx = _load_context(session_id)
    ctx["last_video_qa"] = video_info
    mentioned = ctx.get("mentioned_items", [])
    mentioned.append({
        "type": "video",
        "id": video_info.get("video_id"),
        "title": video_info.get("title"),
    })
    ctx["mentioned_items"] = mentioned[-20:]
    chain = ctx.get("intent_chain", [])
    chain.append("video_qa")
    ctx["intent_chain"] = chain[-10:]
    _save_context(session_id, ctx)


def resolve_references(session_id: str, question: str) -> Dict[str, Any]:
    """
    解析问题中的指代词，返回：
    {
      "resolved": bool,           # 是否解析到指代
      "resolved_question": str,   # 解析后的问题（保持原 question 如果没解析到）
      "referenced_video": dict,   # 被指代的视频（如果有）
      "reference_type": str,      # "ordinal" | "pronoun" | "last_video_qa" | None
      "debug": str,               # 解析说明（debug 用）
    }
    """
    if not session_id or not question:
        return {
            "resolved": False,
            "resolved_question": question,
            "referenced_video": None,
            "reference_type": None,
            "debug": "no session_id or question",
        }

    ctx = _load_context(session_id)
    last_recs = ctx.get("last_recommendations", [])
    last_qa = ctx.get("last_video_qa", {})

    if not last_recs and not last_qa:
        return {
            "resolved": False,
            "resolved_question": question,
            "referenced_video": None,
            "reference_type": None,
            "debug": "no history",
        }

    # 1. 序数词：第二个 / 第 N 个 / 最后一个
    pos_match = _POS_PATTERN.search(question)
    if pos_match:
        text = pos_match.group(1)
        idx = _parse_ordinal_from_pos(text)
        if idx is not None and 0 < idx <= len(last_recs):
            video = last_recs[idx - 1]
            resolved = question[:pos_match.start()] + f"《{video.get('title', '未知')}》" + question[pos_match.end():]
            return {
                "resolved": True,
                "resolved_question": resolved,
                "referenced_video": video,
                "reference_type": "ordinal",
                "debug": f"pos '{text}' → recs[{idx-1}]",
            }
        # 倒数第N个
        if idx is not None and idx < 0:
            real_idx = len(last_recs) + idx + 1
            if 0 < real_idx <= len(last_recs):
                video = last_recs[real_idx - 1]
                resolved = question[:pos_match.start()] + f"《{video.get('title', '未知')}》" + question[pos_match.end():]
                return {
                    "resolved": True,
                    "resolved_question": resolved,
                    "referenced_video": video,
                    "reference_type": "ordinal",
                    "debug": f"pos '{text}' → recs[{real_idx-1}]",
                }

    # 2. 通用序数词：第N个
    ordinal_match = _ORDINAL_PATTERN.search(question)
    if ordinal_match:
        n = _parse_ordinal(ordinal_match.group(1))
        if n and 0 < n <= len(last_recs):
            video = last_recs[n - 1]
            resolved = question[:ordinal_match.start()] + f"《{video.get('title', '未知')}》" + question[ordinal_match.end():]
            return {
                "resolved": True,
                "resolved_question": resolved,
                "referenced_video": video,
                "reference_type": "ordinal",
                "debug": f"ordinal 第{n} → recs[{n-1}]",
            }

    # 3. 代词：这个视频 / 那个视频 / 刚才那个
    pronoun_match = _PRONOUN_PATTERN.search(question)
    if pronoun_match:
        if last_qa and last_qa.get("video_id"):
            resolved = question[:pronoun_match.start()] + f"《{last_qa.get('title', '未知')}》" + question[pronoun_match.end():]
            return {
                "resolved": True,
                "resolved_question": resolved,
                "referenced_video": last_qa,
                "reference_type": "last_video_qa",
                "debug": f"pronoun → last_video_qa",
            }
        if last_recs:
            video = last_recs[0]
            resolved = question[:pronoun_match.start()] + f"《{video.get('title', '未知')}》" + question[pronoun_match.end():]
            return {
                "resolved": True,
                "resolved_question": resolved,
                "referenced_video": video,
                "reference_type": "pronoun",
                "debug": f"pronoun → recs[0]",
            }

    return {
        "resolved": False,
        "resolved_question": question,
        "referenced_video": None,
        "reference_type": None,
        "debug": "no reference pattern matched",
    }


def _parse_ordinal_from_pos(text: str) -> Optional[int]:
    """'第二个' → 2, '最后一个' → -1, '倒数第二个' → -2"""
    mapping = {
        "第一个": 1, "第二个": 2, "第三个": 3, "第四个": 4, "第五个": 5,
        "最后一个": -1, "倒数第一个": -1, "倒数第二个": -2,
    }
    return mapping.get(text)


def get_context_for_query(session_id: str, question: str) -> Dict[str, Any]:
    """
    高阶 API：返回解析后的查询上下文。
    调用方应使用 resolved_question 作为下游 LLM/检索的输入，
    并把 referenced_video 注入到 system prompt。
    """
    resolution = resolve_references(session_id, question)
    ctx = _load_context(session_id)
    return {
        "question": question,
        "resolved_question": resolution["resolved_question"],
        "referenced_video": resolution["referenced_video"],
        "reference_type": resolution["reference_type"],
        "has_history": bool(ctx.get("last_recommendations") or ctx.get("last_video_qa")),
        "last_recommendations": ctx.get("last_recommendations", []),
        "last_video_qa": ctx.get("last_video_qa", {}),
        "intent_chain": ctx.get("intent_chain", []),
    }