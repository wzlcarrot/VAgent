"""可插拔检索通道（借鉴 Ragent SearchChannel，轻量 registry）。"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

ChannelFn = Callable[[str, int, Optional[str]], List[Dict[str, Any]]]


def _keyword_channel(query: str, top_k: int, video_id: Optional[str] = None) -> List[Dict[str, Any]]:
    from app.tools.rag_tools import RAGTools

    try:
        return RAGTools.retrieve_knowledge(query, top_k=top_k, video_id=video_id)
    except Exception as e:
        logger.warning("keyword channel failed: %s", e)
        return []


def _vector_channel(query: str, top_k: int, video_id: Optional[str] = None) -> List[Dict[str, Any]]:
    from app.tools.llm_tools import LLM_tools
    from app.tools.rag_tools import RAGTools

    try:
        embedding = LLM_tools.embed([query])
        if embedding:
            return RAGTools.vector_search(embedding[0], top_k=top_k, video_id=video_id)
    except Exception as e:
        logger.warning("vector channel failed: %s", e)
    return []


def _platform_docs_channel(query: str, top_k: int, video_id: Optional[str] = None) -> List[Dict[str, Any]]:
    from app.tools.rag_tools import RAGTools

    try:
        docs = RAGTools.retrieve_platform_docs(query, top_k=top_k)
        for d in docs:
            d.setdefault("channel", "platform_docs")
        return docs
    except Exception as e:
        logger.warning("platform_docs channel failed: %s", e)
        return []


def web_search_stub(query: str, top_k: int = 3) -> List[Dict[str, Any]]:
    """联网搜索占位：默认返回空；接真实 API 时替换实现即可。"""
    logger.debug("web_search_stub skipped query=%r top_k=%s", query[:80], top_k)
    return []


def _web_channel(query: str, top_k: int, video_id: Optional[str] = None) -> List[Dict[str, Any]]:
    from app.config import settings

    if not settings.web_search_enabled:
        return []
    items = web_search_stub(query, top_k=top_k)
    for d in items:
        d.setdefault("channel", "web")
    return items


CHANNEL_REGISTRY: Dict[str, ChannelFn] = {
    "keyword": _keyword_channel,
    "vector": _vector_channel,
    "platform_docs": _platform_docs_channel,
    "web": _web_channel,
}


def active_channels() -> List[str]:
    from app.config import settings

    names = ["keyword", "vector", "platform_docs"]
    if settings.web_search_enabled:
        names.append("web")
    return names


def multi_channel_recall(
    query: str,
    top_k: int,
    video_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """并行多通道召回后按 content 去重合并（RRF 前并集）。"""
    import concurrent.futures

    channels = active_channels()
    seen = set()
    merged: List[Dict[str, Any]] = []

    def _run(name: str) -> List[Dict[str, Any]]:
        fn = CHANNEL_REGISTRY.get(name)
        if fn is None:
            return []
        docs = fn(query, top_k, video_id)
        for d in docs:
            d.setdefault("channel", name)
        return docs

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(channels) or 1) as ex:
        for docs in ex.map(_run, channels):
            for doc in docs:
                if not isinstance(doc, dict):
                    continue
                content = doc.get("content", doc.get("block_content", "")) or ""
                vid = doc.get("video_id") or ""
                key = f"{vid}:{content[:50]}"
                if key not in seen and content:
                    seen.add(key)
                    merged.append(doc)
    return merged
