#!/usr/bin/env python3
"""意图三分路由回归 CLI。

用法:
  cd ai-end && python3 scripts/intent_ternary_regression.py
  cd ai-end && python3 scripts/intent_ternary_regression.py --fused
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.harness.intent_ternary import run_ternary  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fused", action="store_true", help="跑融合主路径（可能调用 embedding/LLM）")
    args = parser.parse_args()
    report = run_ternary(fused=args.fused)
    print(f"Intent ternary [{report['mode']}]: {report['passed']}/{report['total']} ({report['accuracy']:.1%})")
    for b, st in report["buckets"].items():
        print(f"  [{b}] {st['passed']}/{st['total']}")
    for f in report["failures"]:
        print(f"  ✗ [{f['bucket']}] {f['q']!r} → {f['got']} (expected {f['expected']})")
    ternary_ok = all(
        report["buckets"].get(b, {}).get("passed", 0) / max(1, report["buckets"].get(b, {}).get("total", 1)) >= 0.8
        for b in ("qa", "recommend", "chitchat")
    )
    return 0 if report["accuracy"] >= 0.85 and ternary_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
