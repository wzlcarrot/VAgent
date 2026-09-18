#!/usr/bin/env python3
"""Demo 证据一条龙：自检 → 索引 → warmup → live suite →（可选）15 轮回归。

用法:
  python3 scripts/demo_evidence.py --base http://127.0.0.1:9090 \\
      --email test@viewhub.com --password 123456 \\
      --video-id <ID> --admin-key <ADMIN_API_KEY> --full
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
AI_END = ROOT.parent


def _run(cmd: list[str], label: str) -> int:
    print(f"\n>>> {label}")
    print("    ", " ".join(cmd))
    proc = subprocess.run(cmd, cwd=str(AI_END))
    return proc.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="VAgent demo evidence pipeline")
    parser.add_argument("--base", default="http://127.0.0.1:9090")
    parser.add_argument("--email", default="")
    parser.add_argument("--password", default="")
    parser.add_argument("--video-id", default="")
    parser.add_argument("--admin-key", default="")
    parser.add_argument("--full", action="store_true", help="额外跑 15 轮 viewhub_live_regression")
    parser.add_argument("--skip-warmup", action="store_true")
    args = parser.parse_args()

    py = sys.executable
    common = ["--base", args.base]
    if args.email:
        common += ["--email", args.email, "--password", args.password]
    if args.video_id:
        common += ["--video-id", args.video_id]

    rc = _run(
        [py, str(ROOT / "check_demo_ready.py"), *common,
         *(["--admin-key", args.admin_key] if args.admin_key else []),
         *(["--index-if-missing"] if args.admin_key and args.video_id else [])],
        "1/4 check_demo_ready",
    )
    if rc != 0:
        print("\nPIPELINE FAIL at check_demo_ready")
        return rc

    if not args.skip_warmup:
        rc = _run(
            [py, str(ROOT / "demo_warmup.py"), *common],
            "2/4 demo_warmup",
        )
        if rc != 0:
            print("\nPIPELINE FAIL at demo_warmup")
            return rc
    else:
        print("\n>>> 2/4 demo_warmup SKIPPED")

    suite_cmd = [py, str(ROOT / "sse_live_suite.py"), *common]
    if args.admin_key:
        suite_cmd += ["--admin-key", args.admin_key]
    rc = _run(suite_cmd, "3/4 sse_live_suite")
    if rc != 0:
        print("\nPIPELINE FAIL at sse_live_suite")
        return rc

    if args.full:
        rc = _run(
            [py, str(ROOT / "viewhub_live_regression.py"), *common],
            "4/4 viewhub_live_regression",
        )
        if rc != 0:
            print("\nPIPELINE FAIL at viewhub_live_regression")
            return rc
    else:
        print("\n>>> 4/4 viewhub_live_regression SKIPPED (use --full)")

    print("\nPIPELINE PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
