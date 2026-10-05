#!/usr/bin/env python3
"""汇总业务评测指标，写入 docs/metrics.md（仓库根目录）。

用法:
  cd ai-end && python3 scripts/run_metrics_report.py
"""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AI_END = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "metrics.md"


def _run(cmd: list[str]) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd=str(AI_END), capture_output=True, text=True)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _pytest_count() -> int:
    code, out = _run([sys.executable, "-m", "pytest", "tests", "--collect-only", "-q", "--no-cov"])
    for line in out.splitlines():
        if "tests collected" in line:
            # e.g. "578 tests collected in 1.27s"
            try:
                return int(line.strip().split()[0])
            except ValueError:
                pass
    return -1


def main() -> int:
    lines: list[str] = []
    lines.append("# VAgent 业务评测指标")
    lines.append("")
    lines.append(f"- 生成时间（UTC）：{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("- 场景：ViewHub 视频助手（问答 / 推荐 / 个人数据 / 闲聊）")
    lines.append("")

    # routing golden
    code, out = _run([sys.executable, "scripts/golden_set.py", "--no-llm"])
    lines.append("## 1. 离线路由大盘（fixtures/routing_golden.jsonl）")
    lines.append("")
    lines.append("```")
    lines.append(out.strip() or "(no output)")
    lines.append("```")
    lines.append("")
    lines.append(f"退出码：{code}")
    lines.append("")

    # behavior
    code2, out2 = _run([sys.executable, "scripts/behavior_golden_set.py"])
    lines.append("## 2. 行为 / 工具策略门禁")
    lines.append("")
    lines.append("```")
    lines.append(out2.strip() or "(no output)")
    lines.append("```")
    lines.append("")

    # sse offline
    code3, out3 = _run([sys.executable, "scripts/sse_regression.py", "--offline"])
    lines.append("## 3. SSE 离线回归")
    lines.append("")
    lines.append("```")
    # 截断过长日志，保留末尾
    tail = "\n".join(out3.strip().splitlines()[-40:])
    lines.append(tail or "(no output)")
    lines.append("```")
    lines.append("")

    # synonym
    code4, out4 = _run([sys.executable, "scripts/synonym_video_qa_eval.py"])
    lines.append("## 4. 视频内回答护栏（同义 / 硬负例）")
    lines.append("")
    lines.append("```")
    lines.append(out4.strip().split("## Synonym")[-1] and ("## Synonym" + out4.strip().split("## Synonym")[-1]) or out4.strip())
    lines.append("```")
    lines.append("")

    n_tests = _pytest_count()
    lines.append("## 5. 自动化测试规模")
    lines.append("")
    lines.append(f"- pytest collect：**{n_tests}**")
    lines.append("")

    n_routing = sum(1 for _ in (AI_END / "fixtures" / "routing_golden.jsonl").open(encoding="utf-8"))
    lines.append("## 6. 规模摘要（写简历用）")
    lines.append("")
    lines.append("| 项 | 规模 |")
    lines.append("|----|------|")
    lines.append(f"| 路由评测集 | {n_routing} |")
    lines.append(f"| pytest 收集 | {n_tests} |")
    lines.append("")
    lines.append("复现：")
    lines.append("")
    lines.append("```bash")
    lines.append("cd ai-end")
    lines.append("python3 scripts/golden_set.py --no-llm")
    lines.append("python3 scripts/behavior_golden_set.py")
    lines.append("python3 scripts/sse_regression.py --offline")
    lines.append("python3 scripts/synonym_video_qa_eval.py")
    lines.append("python3 scripts/run_metrics_report.py")
    lines.append("```")
    lines.append("")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT}")
    return 0 if code == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
