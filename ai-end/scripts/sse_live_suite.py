#!/usr/bin/env python3
"""Live SSE 证据套件：登录 →（可选索引）→ video_qa citations → recommend videos。

用法:
  VAGENT_DEMO_MODE=1  # 建议与服务端一致
  python3 scripts/sse_live_suite.py --base http://127.0.0.1:9090 \\
      --email test@viewhub.com --password 123456 \\
      --video-id <已有视频ID> --admin-key <ADMIN_API_KEY>

不传 --admin-key 时跳过索引步骤；citations 断言失败会以非 0 退出（五五开硬门槛）。
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.harness.sse_assert import assert_sequence  # noqa: E402


def _login(base: str, email: str, password: str) -> str:
    url = f"{base.rstrip('/')}/ai/login"
    body = json.dumps({"email": email, "password": password}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    token = (data.get("user") or {}).get("token") or data.get("token")
    if not token:
        raise RuntimeError(f"login failed: {data}")
    return token


def _admin_index(base: str, admin_key: str, video_id: str) -> dict:
    url = f"{base.rstrip('/')}/ai/admin/index-video/{urllib.parse.quote(video_id)}"
    req = urllib.request.Request(
        url, data=b"", method="POST",
        headers={"X-Admin-Key": admin_key},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _collect_sse(base: str, token: str, question: str, video_id: str = "") -> list[dict]:
    url = f"{base.rstrip('/')}/ai/chat/stream"
    payload = {"question": question, "sessionId": "", "videoId": video_id or ""}
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
    )
    events: list[dict] = []
    with urllib.request.urlopen(req, timeout=120) as resp:
        for raw in resp:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data or data == "[DONE]":
                continue
            try:
                events.append(json.loads(data))
            except json.JSONDecodeError:
                continue
    return events


def _run_case(name: str, events: list[dict], expects: list[str]) -> bool:
    print(f"== {name} ==")
    passed, failures = assert_sequence(events, expects)
    for spec in expects:
        print(f"  {'PASS' if spec not in failures else 'FAIL'} {spec}")
    types = [e.get("type") for e in events]
    print(f"  events={len(events)} types_sample={types[:12]}")
    print(f"  result: {passed}/{len(expects)}")
    return not failures


def main() -> int:
    parser = argparse.ArgumentParser(description="VAgent live SSE evidence suite")
    parser.add_argument("--base", default="http://127.0.0.1:9090")
    parser.add_argument("--email", default="")
    parser.add_argument("--password", default="")
    parser.add_argument("--token", default="")
    parser.add_argument("--video-id", default="", help="片内问答 video_id（必填才能硬断言 citations）")
    parser.add_argument("--admin-key", default="", help="可选：索引该视频后再测")
    parser.add_argument("--skip-recommend", action="store_true")
    args = parser.parse_args()

    token = args.token
    if not token:
        if not args.email or not args.password:
            print("need --token or --email + --password", file=sys.stderr)
            return 2
        try:
            token = _login(args.base, args.email, args.password)
        except Exception as e:
            print(f"login failed: {e}", file=sys.stderr)
            return 1

    ok_all = True

    # 0) chat smoke
    try:
        events = _collect_sse(args.base, token, "平台有什么功能")
        if not _run_case("chat_smoke", events, ["stage=routing", "type=text", "stage=done"]):
            ok_all = False
    except Exception as e:
        print(f"chat_smoke error: {e}", file=sys.stderr)
        ok_all = False

    # 1) video_qa + citations
    if not args.video_id:
        print("SKIP video_qa_citations (no --video-id)")
    else:
        if args.admin_key:
            try:
                idx = _admin_index(args.base, args.admin_key, args.video_id)
                print(f"index-video: {idx}")
            except Exception as e:
                print(f"index-video warning: {e}", file=sys.stderr)
        try:
            events = _collect_sse(
                args.base, token, "这个视频讲了什么", args.video_id,
            )
            # 换说法第二刀
            events2 = _collect_sse(
                args.base, token, "帮我总结一下片里的核心观点", args.video_id,
            )
            if not _run_case(
                "video_qa_citations",
                events,
                ["stage=routing", "citations_min=1", "type=text", "stage=done"],
            ):
                ok_all = False
            if not _run_case(
                "video_qa_paraphrase",
                events2,
                ["stage=routing", "citations_min=1", "type=text", "stage=done"],
            ):
                ok_all = False
        except Exception as e:
            print(f"video_qa error: {e}", file=sys.stderr)
            ok_all = False

    # 2) recommend
    if not args.skip_recommend:
        try:
            events = _collect_sse(args.base, token, "推荐一些科技视频")
            # live 可能走澄清；至少要有 text 或 videos
            passed_videos, fail_v = assert_sequence(events, ["videos_min=1"])
            passed_text, fail_t = assert_sequence(events, ["type=text", "stage=done"])
            print("== recommend ==")
            if not fail_v:
                print("  PASS videos_min=1")
            else:
                print("  WARN videos_min=1 (可能触发澄清追问)")
            for spec in ["type=text", "stage=done"]:
                print(f"  {'PASS' if spec not in fail_t else 'FAIL'} {spec}")
            if fail_t:
                ok_all = False
            if fail_v and fail_t:
                ok_all = False
        except Exception as e:
            print(f"recommend error: {e}", file=sys.stderr)
            ok_all = False

    print("LIVE SUITE:", "PASS" if ok_all else "FAIL")
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
