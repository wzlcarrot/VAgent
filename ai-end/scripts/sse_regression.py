#!/usr/bin/env python3
"""SSE 回归：live 服务 或 离线事件夹具。

用法:
  # 离线（CI，不启服务）
  python3 scripts/sse_regression.py --offline

  # live 单剧本
  python3 scripts/sse_regression.py --base http://127.0.0.1:9090 \\
      --email test@viewhub.com --password 123456

  # live 全套
  python3 scripts/sse_regression.py --base http://127.0.0.1:9090 --suite \\
      --email test@viewhub.com --password 123456
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.harness.sse_assert import (  # noqa: E402
    assert_sequence,
    discover_scripts,
    load_events_json,
    load_script,
)

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "sse_scripts"
DEFAULT_SCRIPT = SCRIPTS_DIR / "chat_basic.txt"


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


def _collect_sse_events(base: str, token: str, question: str, video_id: str = "") -> list[dict]:
    url = f"{base.rstrip('/')}/ai/chat/stream"
    payload = {"question": question, "sessionId": "", "videoId": video_id or ""}
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST",
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


def _events_path_for(script: Path) -> Path:
    return script.with_suffix(".events.json")


def run_one(script_path: Path, *, events: list[dict] | None = None, base: str = "", token: str = "") -> tuple[int, int, list[str]]:
    script = load_script(script_path)
    if events is None:
        events = _collect_sse_events(base, token, script.question, script.video_id)
    passed, failures = assert_sequence(events, script.expects)
    for spec in script.expects:
        mark = "PASS" if spec not in failures else "FAIL"
        print(f"  {mark} {spec}")
    return passed, len(script.expects), failures


def run_offline(scripts: list[Path]) -> int:
    total_pass = total_exp = 0
    failed_scripts = 0
    for sp in scripts:
        ep = _events_path_for(sp)
        if not ep.exists():
            print(f"SKIP {sp.name} (no {ep.name})")
            continue
        print(f"SSE offline: {sp.name}")
        events = load_events_json(ep)
        passed, total, failures = run_one(sp, events=events)
        total_pass += passed
        total_exp += total
        if failures:
            failed_scripts += 1
        print(f"  result: {passed}/{total}")
    if total_exp == 0:
        print("no offline fixtures found", file=sys.stderr)
        return 2
    print(f"offline total: {total_pass}/{total_exp} scripts_failed={failed_scripts}")
    return 0 if failed_scripts == 0 and total_pass == total_exp else 1


def run_live(scripts: list[Path], base: str, token: str) -> int:
    total_pass = total_exp = 0
    failed_scripts = 0
    for sp in scripts:
        print(f"SSE live: {sp.name}")
        try:
            passed, total, failures = run_one(sp, base=base, token=token)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")[:300]
            print(f"  HTTP {e.code}: {body}", file=sys.stderr)
            failed_scripts += 1
            continue
        except Exception as e:
            print(f"  error: {e}", file=sys.stderr)
            failed_scripts += 1
            continue
        total_pass += passed
        total_exp += total
        if failures:
            failed_scripts += 1
        print(f"  result: {passed}/{total}")
    print(f"live total: {total_pass}/{total_exp} scripts_failed={failed_scripts}")
    return 0 if failed_scripts == 0 and total_pass == total_exp else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="VAgent SSE regression")
    parser.add_argument("--base", default="http://127.0.0.1:4091")
    parser.add_argument("--token", default="")
    parser.add_argument("--email", default="")
    parser.add_argument("--password", default="")
    parser.add_argument("--script", default="")
    parser.add_argument("--suite", action="store_true", help="跑 fixtures/sse_scripts 下全部 .txt")
    parser.add_argument("--offline", action="store_true", help="用 *.events.json 离线断言（CI）")
    args = parser.parse_args()

    if args.suite or (args.offline and not args.script):
        scripts = discover_scripts(SCRIPTS_DIR, mode="live" if not args.offline else "offline")
    elif args.script:
        scripts = [Path(args.script)]
    else:
        scripts = [DEFAULT_SCRIPT]

    if args.offline:
        if not args.script and not args.suite:
            scripts = discover_scripts(SCRIPTS_DIR, mode="offline")
        return run_offline(scripts)

    token = args.token
    if not token:
        if not args.email or not args.password:
            print("need --token or --email + --password (或改用 --offline)", file=sys.stderr)
            return 2
        try:
            token = _login(args.base, args.email, args.password)
        except Exception as e:
            print(f"login error: {e}", file=sys.stderr)
            return 1

    return run_live(scripts, args.base, token)


if __name__ == "__main__":
    raise SystemExit(main())
