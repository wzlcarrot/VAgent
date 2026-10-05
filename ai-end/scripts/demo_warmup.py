#!/usr/bin/env python3
"""演示前预热：串行提问标准问题清单，让会话/检索链路产生真实数据。

用法：
  python3 scripts/demo_warmup.py --base http://127.0.0.1:4091 --token <jwt>
  python3 scripts/demo_warmup.py --base http://127.0.0.1:4091 --email demo@example.com --password <明文密码>

环境变量：
  VAGENT_DEMO_MODE=1  建议与服务端一致，走 LLM replay（检索/改写/grounding 逻辑与生产一致）。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_QUESTIONS = Path(__file__).resolve().parent.parent / "fixtures" / "demo_questions.txt"


def _load_questions(path: Path) -> list[str]:
    if not path.exists():
        return [
            "这个视频讲了什么？",
            "帮我推荐两个编程视频",
            "我有多少硬币？",
        ]
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            lines.append(s)
    return lines


def _login(base: str, email: str, password: str) -> str:
    url = f"{base.rstrip('/')}/ai/login"
    body = json.dumps({"email": email, "password": password}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    user = data.get("user") or {}
    token = user.get("token") or data.get("token")
    if not token:
        raise RuntimeError(f"登录失败，响应无 token: {data}")
    return token


def _stream_chat(base: str, token: str, question: str, video_id: str | None) -> bool:
    url = f"{base.rstrip('/')}/ai/chat/stream"
    payload = {"question": question, "sessionId": "", "videoId": video_id or ""}
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    got_text = False
    with urllib.request.urlopen(req, timeout=120) as resp:
        for raw in resp:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                evt = json.loads(data)
            except json.JSONDecodeError:
                continue
            if evt.get("type") == "text" and evt.get("content"):
                got_text = True
    return got_text


def main() -> int:
    parser = argparse.ArgumentParser(description="VAgent demo warmup")
    parser.add_argument("--base", default="http://127.0.0.1:4091", help="API 根地址")
    parser.add_argument("--token", default="", help="已有 JWT")
    parser.add_argument("--email", default="", help="登录邮箱（无 token 时）")
    parser.add_argument("--password", default="", help="登录密码（明文，与服务端 LoginRequest 一致）")
    parser.add_argument("--video-id", default="", help="视频内回答上下文 video_id")
    parser.add_argument("--questions", default=str(DEFAULT_QUESTIONS), help="问题清单文件")
    parser.add_argument("--sleep", type=float, default=0.5, help="每轮间隔秒数")
    args = parser.parse_args()

    token = args.token
    if not token:
        if not args.email or not args.password:
            print("需要 --token 或 --email + --password", file=sys.stderr)
            return 2
        token = _login(args.base, args.email, args.password)

    questions = _load_questions(Path(args.questions))
    ok = 0
    for i, q in enumerate(questions, start=1):
        print(f"[{i}/{len(questions)}] {q}")
        try:
            if _stream_chat(args.base, token, q, args.video_id or None):
                ok += 1
                print("  -> ok")
            else:
                print("  -> no text (check logs)")
        except urllib.error.HTTPError as e:
            print(f"  -> HTTP {e.code}: {e.read().decode('utf-8', errors='replace')[:200]}")
        except Exception as e:
            print(f"  -> error: {e}")
        time.sleep(args.sleep)

    print(f"warmup done: {ok}/{len(questions)}")
    return 0 if ok == len(questions) else 1


if __name__ == "__main__":
    raise SystemExit(main())
