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


def _item(title: str, url: str, snippet: str, channel: str) -> Dict[str, Any]:
    return {
        "title": (title or "").strip(),
        "url": (url or "").strip(),
        "content": (snippet or title or "").strip(),
        "channel": channel,
    }


def _search_bing(query: str, top_k: int) -> List[Dict[str, Any]]:
    from app.config import settings

    key = (settings.bing_search_api_key or "").strip()
    if not key:
        return []
    try:
        import httpx
        resp = httpx.get(
            settings.bing_search_endpoint,
            params={"q": query, "count": top_k, "mkt": "zh-CN"},
            headers={"Ocp-Apim-Subscription-Key": key},
            timeout=5.0,
        )
        resp.raise_for_status()
        pages = (resp.json().get("webPages") or {}).get("value") or []
    except Exception as e:
        logger.warning("bing search failed: %s", e)
        return []
    out: List[Dict[str, Any]] = []
    for row in pages[:top_k]:
        if not isinstance(row, dict):
            continue
        item = _item(row.get("name") or "", row.get("url") or "", row.get("snippet") or "", "bing")
        if item["content"]:
            out.append(item)
    return out


def _baidu_skip_url(url: str) -> bool:
    u = (url or "").lower()
    return (not u.startswith("http")) or ("baidu.com" in u) or ("baidustatic.com" in u)


def parse_baidu_results(page: str, top_k: int) -> List[Dict[str, Any]]:
    """从百度结果 HTML 抽落地页。优先稳定字段 mu，不依赖单一 class。"""
    import html as html_lib
    import re

    out: List[Dict[str, Any]] = []
    seen = set()
    patterns = (
        r'"mu"\s*:\s*"(https?://[^"]+)"',
        r"mu&quot;:&quot;(https?://[^&\"<>]+)",
        r'data-log="[^"]*mu&quot;:&quot;(https?:[^"&]+)',
    )
    title_near = re.compile(
        r'class="c-title-text"[^>]*>([^<]{2,80})|<h3[^>]*>\s*<a[^>]*>([^<]{2,80})',
        re.I,
    )
    for pat in patterns:
        for m in re.finditer(pat, page):
            url = html_lib.unescape(m.group(1)).split("&quot;")[0].rstrip("\\")
            if _baidu_skip_url(url) or url in seen:
                continue
            window = page[m.end() : m.end() + 500]
            tm = title_near.search(window)
            title = ""
            if tm:
                title = html_lib.unescape((tm.group(1) or tm.group(2) or "")).strip()
            if not title:
                title = url
            seen.add(url)
            out.append(_item(title, url, title, "baidu"))
            if len(out) >= top_k:
                return out
    return out


def _search_baidu(query: str, top_k: int) -> List[Dict[str, Any]]:
    """百度搜索页抽取（国内可访问）。m 站失败再试 www。"""
    import httpx

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    attempts = (
        ("https://m.baidu.com/s", {"word": query}),
        ("https://www.baidu.com/s", {"wd": query, "ie": "utf-8"}),
    )
    last_err: Optional[Exception] = None
    for url, params in attempts:
        try:
            resp = httpx.get(url, params=params, timeout=5.0, headers=headers)
            resp.raise_for_status()
            items = parse_baidu_results(resp.text, top_k)
            if items:
                return items
        except Exception as e:
            last_err = e
            continue
    if last_err:
        logger.warning("baidu search failed: %s", last_err)
    return []


def web_search(query: str, top_k: int = 3) -> List[Dict[str, Any]]:
    """Bing（有 Key）+ 百度，按 URL 去重后截断。"""
    q = (query or "").strip()
    if not q:
        return []
    merged: List[Dict[str, Any]] = []
    seen = set()
    for item in _search_bing(q, top_k) + _search_baidu(q, top_k):
        key = item.get("url") or item.get("content", "")[:50]
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(item)
        if len(merged) >= top_k:
            break
    return merged


def web_search_stub(query: str, top_k: int = 3) -> List[Dict[str, Any]]:
    """兼容旧名。"""
    return web_search(query, top_k=top_k)


def _web_channel(query: str, top_k: int, video_id: Optional[str] = None) -> List[Dict[str, Any]]:
    import os

    from app.config import settings

    if video_id:
        return []
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return []
    if not settings.web_search_enabled:
        return []
    items = web_search(query, top_k=top_k)
    for d in items:
        d.setdefault("channel", "web")
    return items


CHANNEL_REGISTRY: Dict[str, ChannelFn] = {
    "keyword": _keyword_channel,
    "vector": _vector_channel,
    "platform_docs": _platform_docs_channel,
    "web": _web_channel,
}


def active_channels(video_id: Optional[str] = None) -> List[str]:
    from app.config import settings

    if video_id:
        return ["keyword", "vector"]
    names = ["keyword", "vector", "platform_docs"]
    if settings.web_search_enabled:
        names.append("web")
    return names


def multi_channel_recall(
    query: str,
    top_k: int,
    video_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """并行多通道召回后按「视频 ID + 正文」去重合并。"""
    import concurrent.futures

    channels = active_channels(video_id)
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
