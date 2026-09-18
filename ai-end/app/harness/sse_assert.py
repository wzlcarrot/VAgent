"""SSE 事件断言：剧本解析 + 事件匹配（供 live 回归与离线 CI）。"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class SseScript:
    question: str = ""
    video_id: str = ""
    expects: List[str] = field(default_factory=list)
    path: Optional[Path] = None
    mode: str = "live"  # live | offline


def parse_script(text: str, path: Optional[Path] = None) -> SseScript:
    script = SseScript(path=path)
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            if s.upper().startswith("# MODE "):
                script.mode = s.split(" ", 2)[2].strip().lower()
            continue
        if s.startswith("QUESTION "):
            script.question = s.split(" ", 1)[1].strip().strip('"')
        elif s.startswith("VIDEO_ID "):
            script.video_id = s.split(" ", 1)[1].strip()
        elif s.startswith("EXPECT "):
            script.expects.append(s.split(" ", 1)[1].strip())
    return script


def load_script(path: Path) -> SseScript:
    script = parse_script(path.read_text(encoding="utf-8"), path=path)
    if not script.question:
        raise ValueError(f"script missing QUESTION: {path}")
    if not script.expects:
        raise ValueError(f"script missing EXPECT: {path}")
    return script


def match_event(event: Dict[str, Any], spec: str) -> bool:
    """
    支持：
      type=<name>
      stage=<name>
      tool_start name=<tool>
      tool_end name=<tool>
      text_contains=<substr>
      citations_min=<n>
      meta_winner=<workflow>
      harness=<event>
      retry_op=<op_prefix>   # type=retry 且 op 前缀匹配
      videos_min=<n>
    """
    if spec.startswith("type="):
        return event.get("type") == spec.split("=", 1)[1]
    if spec.startswith("stage="):
        return event.get("type") == "status" and event.get("stage") == spec.split("=", 1)[1]
    if spec.startswith("tool_start "):
        name = spec.split("=", 1)[1]
        return event.get("type") == "tool" and event.get("status") == "start" and event.get("name") == name
    if spec.startswith("tool_end "):
        name = spec.split("=", 1)[1]
        return (
            event.get("type") == "tool"
            and event.get("status") in ("end", "failed")
            and event.get("name") == name
        )
    if spec.startswith("text_contains="):
        needle = spec.split("=", 1)[1]
        return event.get("type") == "text" and needle in (event.get("content") or "")
    if spec.startswith("citations_min="):
        min_count = int(spec.split("=", 1)[1])
        return event.get("type") == "citations" and len(event.get("citations") or []) >= min_count
    if spec.startswith("meta_winner="):
        winner = spec.split("=", 1)[1]
        meta = event.get("meta") or {}
        return event.get("type") == "meta" and meta.get("winner_type") == winner
    if spec.startswith("harness="):
        name = spec.split("=", 1)[1]
        return event.get("type") == "harness" and event.get("event") == name
    if spec.startswith("retry_op="):
        prefix = spec.split("=", 1)[1]
        return event.get("type") == "retry" and str(event.get("op") or "").startswith(prefix)
    if spec.startswith("videos_min="):
        min_count = int(spec.split("=", 1)[1])
        return event.get("type") == "videos" and len(event.get("videos") or []) >= min_count
    return False


def assert_sequence(events: List[Dict[str, Any]], expects: List[str]) -> Tuple[int, List[str]]:
    """顺序匹配：每条 EXPECT 在后续事件中找首次命中。返回 (passed, failures)。"""
    passed = 0
    failures: List[str] = []
    cursor = 0
    for spec in expects:
        found = False
        for i in range(cursor, len(events)):
            if match_event(events[i], spec):
                found = True
                cursor = i + 1
                break
        if found:
            passed += 1
        else:
            failures.append(spec)
    return passed, failures


def load_events_json(path: Path) -> List[Dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "events" in data:
        data = data["events"]
    if not isinstance(data, list):
        raise ValueError(f"events json must be list: {path}")
    return data


def discover_scripts(dir_path: Path, *, mode: Optional[str] = None) -> List[Path]:
    paths = sorted(dir_path.glob("*.txt"))
    if mode is None:
        return paths
    out: List[Path] = []
    for p in paths:
        script = parse_script(p.read_text(encoding="utf-8"), path=p)
        if mode == "offline":
            out.append(p)  # offline 跑全部有 events 的剧本
        elif script.mode != "offline":
            out.append(p)
    return out
