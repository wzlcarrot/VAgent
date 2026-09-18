#!/usr/bin/env python3
"""ViewHub 多轮 live 回归（15 轮 properties 驱动）。

用法:
  python3 scripts/viewhub_live_regression.py --base http://127.0.0.1:9090 \\
      --email test@viewhub.com --password 123456 --video-id <ID>
"""
from __future__ import annotations

import argparse
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.harness.live_client import collect_sse, login, submit_feedback  # noqa: E402
from app.harness.live_regression import load_live_script  # noqa: E402
from app.harness.sse_assert import assert_sequence  # noqa: E402

DEFAULT_SCRIPT = Path(__file__).resolve().parent.parent / "fixtures" / "viewhub_live_turns.properties"


def _match_any(text: str, keywords: list[str]) -> bool:
    if not keywords:
        return True
    blob = (text or "").lower()
    return any(k.lower() in blob for k in keywords)


def run_script(
    base: str,
    token: str,
    script_path: Path,
    *,
    video_id: str = "",
    sleep_s: float = 0.4,
) -> dict:
    script = load_live_script(script_path)
    sessions = {"main": str(uuid.uuid4()), "fresh": str(uuid.uuid4())}
    last_videos: list = []
    passed = 0
    failures = []

    print(f"ViewHub live regression: {script_path.name} turns={len(script.turn_refs)}")
    print(f"  main_session={sessions['main'][:8]}... fresh_session={sessions['fresh'][:8]}...")

    for ref in script.turn_refs:
        turn = script.turns.get(ref)
        if not turn or not turn.text:
            failures.append({"ref": ref, "reason": "empty turn"})
            continue

        sid = sessions.get(turn.session, sessions["main"])
        vid = turn.video_id or video_id
        print(f"\n-- {ref} [{turn.session}] {turn.purpose or turn.text[:40]}")

        try:
            stream = collect_sse(base, token, turn.text, video_id=vid, session_id=sid)
        except Exception as e:
            print(f"  FAIL stream: {e}")
            failures.append({"ref": ref, "reason": str(e)})
            continue

        if turn.expect_sse:
            p, fail_sse = assert_sequence(stream.events, turn.expect_sse)
            for spec in turn.expect_sse:
                print(f"  {'PASS' if spec not in fail_sse else 'FAIL'} sse {spec}")
            if fail_sse:
                failures.append({"ref": ref, "reason": f"sse:{fail_sse}"})
                continue

        if turn.expect_any:
            if _match_any(stream.text, turn.expect_any):
                print(f"  PASS expect-any {turn.expect_any[:2]}...")
            else:
                print(f"  FAIL expect-any {turn.expect_any} got={stream.text[:120]!r}")
                failures.append({"ref": ref, "reason": "expect-any"})
                continue

        if stream.videos:
            last_videos = stream.videos

        if turn.feedback in ("helpful", "not_helpful"):
            vids = []
            if turn.feedback_videos_from_last and last_videos:
                for v in last_videos:
                    vid_key = v.get("videoId") or v.get("video_id") or ""
                    if vid_key:
                        vids.append(str(vid_key))
            try:
                submit_feedback(
                    base, token,
                    session_id=sid,
                    feedback=turn.feedback,
                    message_index=0,
                    video_ids=vids,
                    question=turn.text,
                    answer=stream.text[:500],
                )
                print(f"  PASS feedback {turn.feedback} videos={len(vids)}")
            except Exception as e:
                print(f"  WARN feedback failed: {e}")

        passed += 1
        time.sleep(sleep_s)

    total = len(script.turn_refs)
    return {
        "passed": passed,
        "total": total,
        "failures": failures,
        "accuracy": passed / total if total else 0.0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:9090")
    parser.add_argument("--email", default="")
    parser.add_argument("--password", default="")
    parser.add_argument("--token", default="")
    parser.add_argument("--video-id", default="", help="注入 t05/t06 等片内问答")
    parser.add_argument("--script", default=str(DEFAULT_SCRIPT))
    parser.add_argument("--sleep", type=float, default=0.4)
    parser.add_argument("--min-accuracy", type=float, default=0.85)
    args = parser.parse_args()

    token = args.token
    if not token:
        if not args.email or not args.password:
            print("need --token or --email + --password", file=sys.stderr)
            return 2
        token = login(args.base, args.email, args.password)

    report = run_script(
        args.base, token, Path(args.script),
        video_id=args.video_id,
        sleep_s=args.sleep,
    )
    print(f"\nresult: {report['passed']}/{report['total']} ({report['accuracy']:.1%})")
    for f in report["failures"]:
        print(f"  ✗ {f}")
    floor = max(0.0, min(1.0, args.min_accuracy))
    return 0 if report["accuracy"] >= floor and not report["failures"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
