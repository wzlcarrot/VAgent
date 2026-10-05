#!/usr/bin/env python3
"""CI 只锁离线可复现数字。live 大盘（如 80.7%）禁止当门禁。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "eval_retrieval_metrics.py"),
        "--min-recall-at-5",
        "0.70",
    ]
    print("CI 检索门禁: offline recall@5 >= 70%（词面基线，不是 live LLM）")
    return subprocess.call(cmd, cwd=str(ROOT))


if __name__ == "__main__":
    sys.exit(main())
