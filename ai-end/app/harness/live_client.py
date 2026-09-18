"""Live 回归共用 HTTP/SSE 客户端（check / warmup / suite / 多轮剧本）。"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class StreamResult:
    events: List[Dict[str, Any]] = field(default_factory=list)
    text: str = ""
    session_id: str = ""
    videos: List[Dict[str, Any]] = field(default_factory=list)
    citations: List[Dict[str, Any]] = field(default_factory=list)


def login(base: str, email: str, password: str) -> str:
    url = f"{base.rstrip('/')}/ai/login"
    body = json.dumps({"email": email, "password": password}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    token = (data.get("user") or {}).get("token") or data.get("token")
    if not token:
        raise RuntimeError(f"login failed: {data}")
    return token


def get_ready(base: str) -> Dict[str, Any]:
    url = f"{base.rstrip('/')}/ready"
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_health(base: str) -> Dict[str, Any]:
    url = f"{base.rstrip('/')}/health"
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def admin_index_video(base: str, admin_key: str, video_id: str) -> Dict[str, Any]:
    url = f"{base.rstrip('/')}/ai/admin/index-video/{urllib.parse.quote(video_id)}"
    req = urllib.request.Request(url, data=b"", method="POST", headers={"X-Admin-Key": admin_key})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def admin_index_stats(base: str, admin_key: str) -> Dict[str, Any]:
    url = f"{base.rstrip('/')}/ai/admin/index-stats"
    req = urllib.request.Request(url, method="GET", headers={"X-Admin-Key": admin_key})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def admin_reindex_pending(base: str, admin_key: str, limit: int = 10) -> Dict[str, Any]:
    url = f"{base.rstrip('/')}/ai/admin/reindex-pending?limit={limit}"
    req = urllib.request.Request(url, data=b"", method="POST", headers={"X-Admin-Key": admin_key})
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read().decode("utf-8"))


def submit_feedback(
    base: str,
    token: str,
    *,
    session_id: str,
    feedback: str,
    message_index: int = 0,
    video_ids: Optional[List[str]] = None,
    question: str = "",
    answer: str = "",
) -> Dict[str, Any]:
    url = f"{base.rstrip('/')}/ai/feedback"
    payload = {
        "session_id": session_id,
        "message_index": message_index,
        "feedback": feedback,
        "video_ids": video_ids or [],
        "question": question,
        "answer": answer,
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def collect_sse(
    base: str,
    token: str,
    question: str,
    *,
    video_id: str = "",
    session_id: str = "",
) -> StreamResult:
    url = f"{base.rstrip('/')}/ai/chat/stream"
    payload: Dict[str, Any] = {
        "question": question,
        "sessionId": session_id or "",
        "videoId": video_id or "",
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
    )
    result = StreamResult()
    with urllib.request.urlopen(req, timeout=120) as resp:
        for raw in resp:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data or data == "[DONE]":
                continue
            try:
                evt = json.loads(data)
            except json.JSONDecodeError:
                continue
            result.events.append(evt)
            et = evt.get("type")
            if et == "text" and evt.get("content"):
                result.text += evt.get("content") or ""
            elif et == "videos" and evt.get("videos"):
                result.videos = evt.get("videos") or []
            elif et == "citations" and evt.get("citations"):
                result.citations = evt.get("citations") or []
            elif et == "harness" and evt.get("event") == "run_end":
                rid = (evt.get("payload") or {}).get("run_id")
                if rid and not result.session_id:
                    pass
    return result
