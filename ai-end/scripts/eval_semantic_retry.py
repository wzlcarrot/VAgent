#!/usr/bin/env python3
"""
语义级重试（Semantic Retry）ablation —— 首轮召回不足时，换角度重试能否提升证据充足率。

为什么是"受控模拟"：
    离线环境无 DB / pgvector（真实检索不可用），用一个受控检索模型代替——
    查询命中该视频的某个"内容词（gold_terms）"即视为召回充足。
    这模拟真实场景：视频内容术语只在字幕里出现，首轮口语 query 命中不到，
    换一个包含内容术语的角度才检索得到。

对比：
    OFF  关闭语义重试（只用首轮 rewrite）
    ON   开启语义重试（不足时换角度，最多 N 轮）

指标：
    证据充足率      OFF vs ON
    净增益          首轮失败的样本里，ON 救回的比例
    平均检索次数    OFF vs ON（重试的成本）

用法:
    cd ai-end
    python3 scripts/eval_semantic_retry.py                 # 真实 LLM 改写（默认，需 DEEPSEEK_API_KEY）
    python3 scripts/eval_semantic_retry.py --runs 3        # 多轮取均值，降低 LLM 随机性波动
    python3 scripts/eval_semantic_retry.py --offline       # 规则回退改写（零 token）
    python3 scripts/eval_semantic_retry.py --limit 5
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "semantic_retry_cases.jsonl"

_CURRENT_GOLD: List[str] = []
_CURRENT_QUERIES: List[str] = []


def load_cases() -> List[dict]:
    rows = []
    for line in FIXTURE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def _hit(query: str) -> bool:
    q = (query or "").lower()
    return any(term.lower() in q for term in _CURRENT_GOLD)


def _sim_search(session_id: str, video_id: str, query: str, title: str, tags: str, top_k: int):
    """受控检索：命中内容词 → 充足；否则弱相关。"""
    _CURRENT_QUERIES.append(query or "")
    if _hit(query):
        return ([{"video_id": video_id, "content": f"命中内容词：{query}", "score": 0.9}], True)
    return ([{"video_id": video_id, "content": "弱相关片段", "score": 0.05}], False)


def _install_mocks() -> None:
    import app.agents.video_qa_react as vq

    vq._execute_search_tool = _sim_search  # type: ignore[assignment]
    vq.search_video_chunks = (  # type: ignore[assignment]
        lambda video_id, question, **kwargs: _sim_search("", video_id, question, "", "", 5)
    )


def _configure(live: bool) -> None:
    from app.config import settings

    settings.video_qa_react_enabled = True
    settings.video_qa_react_max_steps = 3
    settings.video_qa_semantic_retry_max = 1
    if live:
        settings.demo_mode = False
        settings.llm_replay_enabled = False
    else:
        settings.demo_mode = True


def run_one(tc: dict, retry_on: bool, session_id: str) -> Dict[str, Any]:
    from app.agents.video_qa_react import run_video_qa_react_retrieval
    from app.config import settings

    global _CURRENT_GOLD, _CURRENT_QUERIES
    _CURRENT_GOLD = list(tc.get("gold_terms") or [])
    _CURRENT_QUERIES = []
    settings.video_qa_semantic_retry_enabled = retry_on

    knowledge, sufficient, steps, _, _stop = run_video_qa_react_retrieval(
        video_id=tc.get("video_id") or "video_demo_001",
        question=tc["q"],
        title=tc.get("title", ""),
        tags=tc.get("tags", ""),
        session_id=session_id,
    )
    return {
        "q": tc["q"],
        "title": tc.get("title", ""),
        "gold": tc.get("gold_terms") or [],
        "sufficient": bool(sufficient),
        "steps": int(steps),
        "queries": list(_CURRENT_QUERIES),
        "hits": len(knowledge),
    }


def run_trial(cases: List[dict], trial_idx: int) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for i, tc in enumerate(cases, 1):
        off = run_one(tc, retry_on=False, session_id=f"sr{trial_idx}_off_{i}")
        on = run_one(tc, retry_on=True, session_id=f"sr{trial_idx}_on_{i}")
        rows.append({"case": tc, "off": off, "on": on})
    return rows


def summarize(rows: List[Dict[str, Any]], elapsed: float) -> Dict[str, float]:
    n = len(rows)
    off_ok = sum(1 for r in rows if r["off"]["sufficient"])
    on_ok = sum(1 for r in rows if r["on"]["sufficient"])
    off_miss = [r for r in rows if not r["off"]["sufficient"]]
    rescued = sum(1 for r in off_miss if r["on"]["sufficient"])
    return {
        "n": n,
        "off_rate": off_ok / max(n, 1) * 100,
        "on_rate": on_ok / max(n, 1) * 100,
        "off_ok": off_ok,
        "on_ok": on_ok,
        "off_miss": len(off_miss),
        "rescued": rescued,
        "rescue_rate": rescued / max(len(off_miss), 1) * 100,
        "off_q": sum(len(r["off"]["queries"]) for r in rows) / max(n, 1),
        "on_q": sum(len(r["on"]["queries"]) for r in rows) / max(n, 1),
        "elapsed": elapsed,
    }


def _print_summary(s: Dict[str, float], tag: str = "") -> None:
    print(
        f"  {tag}OFF {s['off_rate']:5.1f}% ({int(s['off_ok'])}/{int(s['n'])})   "
        f"ON {s['on_rate']:5.1f}% ({int(s['on_ok'])}/{int(s['n'])})   "
        f"救回 {s['rescue_rate']:5.1f}% ({int(s['rescued'])}/{int(s['off_miss'])})   "
        f"检索次数 {s['off_q']:.2f}→{s['on_q']:.2f}"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true", help="规则回退改写（默认真实 LLM）")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--runs", type=int, default=1, help="重复轮数，取均值降低随机波动")
    args = parser.parse_args()

    live = not args.offline
    cases = load_cases()
    if args.limit:
        cases = cases[: args.limit]

    _install_mocks()
    _configure(live)

    mode = "live(真实 LLM 改写)" if live else "offline(规则回退改写)"
    print(f"模式: {mode}   用例: {len(cases)}   轮数: {args.runs}")

    trials: List[Dict[str, float]] = []
    t0 = time.time()
    for t in range(1, args.runs + 1):
        tt = time.time()
        rows = run_trial(cases, t)
        s = summarize(rows, time.time() - tt)
        trials.append(s)
        _print_summary(s, tag=f"[第 {t} 轮] ")
        if t == args.runs:
            for r in rows:
                if not r["off"]["sufficient"] and not r["on"]["sufficient"]:
                    print(f"  ⚠️ 仍未救回  {r['case']['title']}  gold={r['case']['gold_terms']}")
    elapsed = time.time() - t0

    print("=" * 66)
    print("  语义级重试 ablation（受控模拟检索）")
    print("=" * 66)
    if len(trials) == 1:
        s = trials[0]
        print(f"  证据充足率 OFF   {s['off_rate']:.1f}% ({int(s['off_ok'])}/{int(s['n'])})")
        print(f"  证据充足率 ON    {s['on_rate']:.1f}% ({int(s['on_ok'])}/{int(s['n'])})")
        print(f"  净增益           {s['rescue_rate']:.1f}% ({int(s['rescued'])}/{int(s['off_miss'])})")
        print(f"  平均检索次数     OFF {s['off_q']:.2f}  →  ON {s['on_q']:.2f}")
    else:
        off = [s["off_rate"] for s in trials]
        on = [s["on_rate"] for s in trials]
        res = [s["rescue_rate"] for s in trials]
        oq = [s["off_q"] for s in trials]
        nq = [s["on_q"] for s in trials]
        print(f"  证据充足率 OFF   均值 {statistics.mean(off):.1f}%   区间 {min(off):.1f}–{max(off):.1f}%")
        print(f"  证据充足率 ON    均值 {statistics.mean(on):.1f}%   区间 {min(on):.1f}–{max(on):.1f}%")
        print(f"  净增益（救回）   均值 {statistics.mean(res):.1f}%   区间 {min(res):.1f}–{max(res):.1f}%")
        print(f"  平均检索次数     OFF {statistics.mean(oq):.2f}  →  ON {statistics.mean(nq):.2f}")
    print(f"  总耗时           {elapsed:.1f}s")
    print("=" * 66)

    return 0


if __name__ == "__main__":
    sys.exit(main())
