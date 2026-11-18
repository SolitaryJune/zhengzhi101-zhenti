#!/usr/bin/env python3
"""校验政治101真题站的讲解与动画覆盖率/完整性（同 math302 校验器逻辑）。

stdout 只输出一个 JSON（供工作流门禁解析）：
  {total, ok, bad}
诊断信息走 stderr。

检查项（存在性 + 动画引擎 + 大小阈值）：
  - 讲解 data/explain/{id}.md 存在且不少于 MIN_EXPLAIN 字节
  - 动画 anim/{id}.html 存在且不少于 MIN_ANIM 字节（占位页约 0.6KB）
  - 真实动画须使用动画引擎：含 AW.init 或引用 anim-engine.js（模板约定）
  与 math302 版的差异：政治站无数学公式、不内嵌 KaTeX，
  故不检查「anim 未引用 KaTeX」项。
"""
import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
MIN_ANIM = 1500    # 占位页约 0.6KB，真实动画至少 1.5KB
MIN_EXPLAIN = 150


def load_ids() -> list[str]:
    """题号列表来自 data/meta.json 的 years + 各年 questions[].id；
    meta 缺失时回退扫描 data/questions/*.json。"""
    qdir = PROJECT / "data" / "questions"
    years: list[int] = []
    meta_path = PROJECT / "data" / "meta.json"
    if meta_path.exists():
        try:
            years = [int(y) for y in json.loads(meta_path.read_text(encoding="utf-8")).get("years") or []]
        except (ValueError, OSError):
            years = []
    if not years:
        years = sorted(int(p.stem) for p in qdir.glob("*.json") if p.stem.isdigit())
    ids: list[str] = []
    for y in years:
        f = qdir / f"{y}.json"
        try:
            payload = json.loads(f.read_text(encoding="utf-8"))
        except (ValueError, OSError) as e:
            print(f"{y}.json 读取失败: {e}", file=sys.stderr)
            continue
        qs = payload.get("questions") if isinstance(payload, dict) else payload
        ids += [q["id"] for q in (qs or [])]
    return ids


def main() -> int:
    ids = load_ids()
    bad = []
    ok = 0
    for qid in ids:
        exp = PROJECT / "data" / "explain" / f"{qid}.md"
        anim = PROJECT / "anim" / f"{qid}.html"
        try:
            e_len = exp.stat().st_size if exp.exists() else 0
            a_len = anim.stat().st_size if anim.exists() else 0
        except OSError:
            bad.append(qid)
            continue
        problems = []
        if e_len < MIN_EXPLAIN:
            problems.append("explain缺失或过短")
        if a_len < MIN_ANIM:
            problems.append("anim缺失或为占位")
        else:
            content = anim.read_text(encoding="utf-8", errors="ignore")
            if "AW.init" not in content and "anim-engine.js" not in content:
                problems.append("anim未使用动画引擎")
        if problems:
            bad.append(qid)
            print(f"{qid}: {', '.join(problems)}", file=sys.stderr)
        else:
            ok += 1
    result = {"total": len(ids), "ok": ok, "bad": bad}
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
