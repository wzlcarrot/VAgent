"""ViewHub 多轮 live 回归剧本解析（借鉴 Ragent turns.properties）。"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class LiveTurn:
    ref: str
    session: str = "main"  # main | fresh
    text: str = ""
    video_id: str = ""
    purpose: str = ""
    expect_any: List[str] = field(default_factory=list)
    expect_sse: List[str] = field(default_factory=list)
    feedback: str = ""  # helpful | not_helpful
    feedback_videos_from_last: bool = False


@dataclass
class LiveScript:
    anchor: str = ""
    turn_refs: List[str] = field(default_factory=list)
    turns: Dict[str, LiveTurn] = field(default_factory=dict)
    path: Optional[Path] = None


def parse_live_script(text: str, path: Optional[Path] = None) -> LiveScript:
    script = LiveScript(path=path)
    turn_buf: Dict[str, Dict[str, str]] = {}

    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if "=" not in s:
            continue
        key, val = s.split("=", 1)
        key = key.strip()
        val = val.strip()

        if key == "anchor":
            script.anchor = val
            continue
        if key == "turn.refs":
            script.turn_refs = [x.strip() for x in val.split(",") if x.strip()]
            continue
        if key.startswith("turn.") and "." in key[5:]:
            _, rest = key.split(".", 1)
            ref, field_name = rest.split(".", 1)
            turn_buf.setdefault(ref, {})[field_name] = val

    for ref in script.turn_refs:
        raw = turn_buf.get(ref, {})
        expect_any = [x.strip() for x in (raw.get("expect-any") or "").split("|") if x.strip()]
        expect_sse = [x.strip() for x in (raw.get("expect-sse") or "").split("|") if x.strip()]
        script.turns[ref] = LiveTurn(
            ref=ref,
            session=(raw.get("session") or "main").lower(),
            text=raw.get("text") or "",
            video_id=raw.get("video_id") or raw.get("video-id") or "",
            purpose=raw.get("purpose") or "",
            expect_any=expect_any,
            expect_sse=expect_sse,
            feedback=(raw.get("feedback") or "").lower(),
            feedback_videos_from_last=(raw.get("feedback-videos") or "").lower() in ("1", "true", "yes"),
        )
    return script


def load_live_script(path: Path) -> LiveScript:
    return parse_live_script(path.read_text(encoding="utf-8"), path=path)
