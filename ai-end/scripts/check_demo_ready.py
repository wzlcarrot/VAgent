#!/usr/bin/env python3
"""Demo 环境自检：/health /ready /login /索引 /citations 探针。

用法:
  python3 scripts/check_demo_ready.py --base http://127.0.0.1:9090 \\
      --email test@viewhub.com --password 123456 \\
      --video-id <ID> --admin-key <KEY>
"""
from __future__ import annotations

import argparse
import sys
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.harness.live_client import (  # noqa: E402
    admin_index_stats,
    admin_index_video,
    collect_sse,
    get_health,
    get_ready,
    login,
)
from app.harness.sse_assert import assert_sequence  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="VAgent demo readiness check")
    parser.add_argument("--base", default="http://127.0.0.1:9090")
    parser.add_argument("--email", default="")
    parser.add_argument("--password", default="")
    parser.add_argument("--video-id", default="")
    parser.add_argument("--admin-key", default="")
    parser.add_argument("--index-if-missing", action="store_true")
    args = parser.parse_args()

    ok = True
    print("== check_demo_ready ==")

    try:
        h = get_health(args.base)
        print(f"  PASS health {h}")
    except Exception as e:
        print(f"  FAIL health: {e}")
        ok = False

    try:
        r = get_ready(args.base)
        checks = {k: r.get(k) for k in ("db", "redis", "llm") if k in r}
        bad = [k for k, v in checks.items() if not v]
        if bad:
            print(f"  WARN ready partial fail: {checks}")
        else:
            print(f"  PASS ready {checks}")
    except Exception as e:
        print(f"  FAIL ready: {e}")
        ok = False

    token = ""
    if args.email and args.password:
        try:
            token = login(args.base, args.email, args.password)
            print("  PASS login")
        except Exception as e:
            print(f"  FAIL login: {e}")
            ok = False
    else:
        print("  SKIP login (no --email/--password)")

    if args.admin_key:
        try:
            stats = admin_index_stats(args.base, args.admin_key)
            print(f"  PASS index-stats videos_indexed={stats.get('videos_indexed')} pending={stats.get('videos_pending')}")
            vid = args.video_id
            if vid and args.index_if_missing:
                pending = stats.get("pending_sample") or []
                if vid in pending or (stats.get("videos_pending") or 0) > 0:
                    idx = admin_index_video(args.base, args.admin_key, vid)
                    print(f"  INFO index-video {vid}: {idx.get('success', idx)}")
        except urllib.error.HTTPError as e:
            print(f"  FAIL index-stats HTTP {e.code}")
            ok = False
        except Exception as e:
            print(f"  FAIL index-stats: {e}")
            ok = False
    else:
        print("  SKIP index-stats (no --admin-key)")

    if token and args.video_id:
        try:
            stream = collect_sse(
                args.base, token, "这个视频讲了什么", video_id=args.video_id,
            )
            passed, failures = assert_sequence(
                stream.events,
                ["stage=routing", "citations_min=1", "type=text", "stage=done"],
            )
            if failures:
                print(f"  WARN citations probe: missing {failures} (索引/向量可能未就绪)")
                print(f"       events_types={[e.get('type') for e in stream.events[:15]]}")
            else:
                print(f"  PASS citations probe ({passed}/4)")
        except Exception as e:
            print(f"  FAIL citations probe: {e}")
            ok = False
    elif args.video_id:
        print("  SKIP citations probe (login failed)")
    else:
        print("  SKIP citations probe (no --video-id)")

    print("RESULT:", "READY" if ok else "NOT_READY")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
