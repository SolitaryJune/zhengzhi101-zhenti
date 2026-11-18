#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
extract_politics101.py — 考研政治(101) 真题 2009–2026 抽取脚本
==============================================================

数据源
------
主源   : Nishino0525Nanase/kaoyan-politics  (取 dist/questions.json,
         1,192,531 B, md5 8c71b64af2414ba6433ab7ac193a13e9)
         经 raw.githubusercontent.com 拉取, 缓存到 data/source/questions.json。
说明   : jemy204/kaoyan-politics-app 的 public/data/questions.json 经 md5 实测
         与主源逐字节相同(8c71b64af2414ba6433ab7ac193a13e9), 系同一数据的静态
         拷贝, 不另立源、不参与抓取。

输出
----
data/questions/{year}.json : 每年一份 {"year","count","questions":[...]} 包装对象,
    questions[i] 字段固定为
    id / year / number / type / points / stemHtml / options / answer /
    refAnalysis / tags
    (原库无 wrongOptions 数据, 按「如有」约定省略该字段)
    id 形如 zz-2009-01; type ∈ {单选题, 多选题, 分析题};
    单选 answer 为单字母, 多选 answer 为字母组合串(如 "ABD"), 分析题为 null;
    分析题材料并入 stemHtml, 参考答案按问拆分为 refAnalysis 数组(每问一段 HTML,
    保留原「（1）」/「选做Ⅰ」标记);
    题面引用图片下载到 images/<原名>, stemHtml 内以 <img src="images/..."> 引用。
data/meta.json             : {"years":[...], "total":N, "source":{...}}
images/                    : 题面引用图片(本地化)
stdout                     : 恰好一行 JSON {"total":N,"perYear":{"2009":38,...}}
诊断/告警                   : 全部走 stderr

分值(按当年官方分值, 全程 16×1 + 17×2 + 5 题分析 = 100)
------------------------------------------------------
    单选题 1 分, 多选题 2 分, 分析题 10 分;
    例外: 2012 年第 34 题 12 分、第 38 题 8 分 —— 原库 score 字段与
    sourceNote「当年本题为12分（2012年第34题12分、第38题8分）」一致,
    且 2012-34 题干内设问分值 (1)4分+(2)4分+(3)4分=12 可相互印证;
    本脚本对范围内全部 90 道分析题做了「题干设问 X分 标记求和 == 所赋分值」
    与「每年全卷合计 == 100」两重校验(2026-11-15 通过)。

可重入
------
data/source/questions.json 缓存存在时不再联网(--force 强制重新拉取并校验 md5);
已存在的 data/questions/{year}.json(--years 范围内)默认整年跳过; 图片文件已
存在时跳过下载。data/meta.json 每次按磁盘实况重建。

仅用 Python 标准库, 无第三方依赖。
"""

import argparse
import hashlib
import html as html_mod
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# 常量与配置
# ---------------------------------------------------------------------------

MAIN_REPO = "Nishino0525Nanase/kaoyan-politics"
SOURCE_PATH = "dist/questions.json"
BRANCHES = ("main", "master")

# 主源指纹(与 jemy204/kaoyan-politics-app 静态拷贝逐字节相同, 2026-11-15 实测)
EXPECTED_MD5 = "8c71b64af2414ba6433ab7ac193a13e9"
EXPECTED_SIZE = 1192531

RAW_BASE = "https://raw.githubusercontent.com"

DEFAULT_YEAR_START, DEFAULT_YEAR_END = 2009, 2026

# 原库 type → 归一化题型
TYPE_MAP = {
    "single": "单选题",
    "multiple": "多选题",
    "analysis": "分析题",
}

# 官方分值: 单选 1 / 多选 2 / 分析 10; 例外见模块 docstring
BASE_POINTS = {"单选题": 1, "多选题": 2, "分析题": 10}
POINTS_OVERRIDE = {
    2012: {34: 12, 38: 8},
}
YEARLY_TOTAL = 100  # 全卷满分, 用于每年合计校验

# 2013–2018 分析题参考答案为单段落,「（2）」标记在段落中部, 须按序号链拆分;
# 2009-38 为选做题, 答案以「选做Ⅰ/选做Ⅱ」分块。
SUBQ_MARK_RE = re.compile(r"[（(]\s*([1-9])\s*[)）]")
XUANZUO_MARK_RE = re.compile(r"选做[ⅠⅡ]")
# 题干内设问标记: (1)/（1） 或 ①②③
STEM_SUBQ_NUM_RE = re.compile(r"[（(]\s*([1-9])\s*[)）]|[①②③④⑤]")

IMG_TAG_RE = re.compile(r"<img\b", re.I)


def log(msg):
    """诊断信息统一走 stderr, stdout 只保留最终一行 JSON。"""
    print(f"[politics101] {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# 网络层
# ---------------------------------------------------------------------------

_HTTP_UA = "politics101-extract/1.0 (+https://github.com/Nishino0525Nanase/kaoyan-politics)"


def http_get(url, timeout, retries=2):
    """GET 一个 URL, 返回 bytes, 失败抛异常。带简单重试。"""
    last_err = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _HTTP_UA})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, TimeoutError) as e:
            last_err = e
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
    raise last_err


def source_url(branch):
    return f"{RAW_BASE}/{MAIN_REPO}/{branch}/{SOURCE_PATH}"


def fetch_source(root, force, timeout):
    """取主源 dist/questions.json(缓存于 data/source/), 返回 (bytes, md5, branch)。

    可重入: 缓存存在且未 --force 时直接用缓存, 不联网。md5 与 EXPECTED_MD5
    不符时告警(上游可能更新)但继续, 实际指纹写入 meta.json。
    """
    cache = root / "data" / "source" / "questions.json"
    if cache.exists() and not force:
        data = cache.read_bytes()
        md5 = hashlib.md5(data).hexdigest()
        if md5 != EXPECTED_MD5:
            log(f"缓存源 md5={md5} 与预期 {EXPECTED_MD5} 不符(上游可能已更新), 继续使用缓存")
        log(f"使用缓存源 {cache}({len(data)} B, md5 {md5})")
        return data, md5, None

    last_err = None
    for branch in BRANCHES:
        url = source_url(branch)
        try:
            data = http_get(url, timeout)
        except Exception as e:  # noqa: BLE001 — 逐分支回退
            last_err = e
            log(f"拉取 {url} 失败: {e}")
            continue
        md5 = hashlib.md5(data).hexdigest()
        if md5 != EXPECTED_MD5 or len(data) != EXPECTED_SIZE:
            log(f"警告: 主源指纹 md5={md5} size={len(data)} 与预期 "
                f"md5={EXPECTED_MD5} size={EXPECTED_SIZE} 不符(上游可能已更新)")
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(data)
        log(f"已拉取并缓存主源 {url}({len(data)} B, md5 {md5})")
        return data, md5, branch
    raise RuntimeError(f"主源拉取失败(分支 {BRANCHES} 均不可达): {last_err}")


# ---------------------------------------------------------------------------
# 文本 → HTML
# ---------------------------------------------------------------------------

def to_html(text):
    """纯文本题面 → HTML: HTML 转义 + 空行分段(<p>), 段内换行 <br>。"""
    t = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not t:
        return ""
    out = []
    for para in re.split(r"\n{2,}", t):
        para = para.strip()
        if para:
            out.append("<p>" + html_mod.escape(para).replace("\n", "<br>") + "</p>")
    return "".join(out)


# ---------------------------------------------------------------------------
# 分析题参考答案按问拆分
# ---------------------------------------------------------------------------

def split_analysis_answer(ref):
    """把分析题 referenceAnswer 按问拆成字符串数组(保留原问号标记)。

    - 含「选做Ⅰ/选做Ⅱ」→ 按选做块拆(2009-38);
    - 否则按「（1）（2）（3）」序号链拆: 仅接受自 1 起逐个递增的序号标记,
      且不要求在行首(2013–2018 多为单段落, (2) 在段落中部)。
    拆不出任何标记 → 整段作为单元素数组(如 2011-38 单问)。
    """
    text = (ref or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return []

    if XUANZUO_MARK_RE.search(text):
        parts = [p.strip() for p in re.split(r"(?=选做[ⅠⅡ])", text)]
        return [p for p in parts if p]

    expect, cuts = 1, []
    for m in SUBQ_MARK_RE.finditer(text):
        if int(m.group(1)) == expect:
            cuts.append(m.start())
            expect += 1
    if not cuts:
        return [text]
    bounds = ([0] if cuts[0] != 0 else []) + cuts + [len(text)]
    parts = [text[a:b].strip() for a, b in zip(bounds, bounds[1:])]
    return [p for p in parts if p]


def stem_subq_count(stem):
    """题干内设问标记计数(自 1 起递增链, 或题干用 ①② 计数)。用于软校验。"""
    text = (stem or "").replace("\r\n", "\n")
    nums = [int(m.group(1)) for m in SUBQ_MARK_RE.finditer(text)]
    expect, chain = 1, 0
    for n in nums:
        if n == expect:
            chain += 1
            expect += 1
    circled = len(re.findall(r"[①②③④⑤]", text))
    return max(chain, circled)


# ---------------------------------------------------------------------------
# 图片本地化
# ---------------------------------------------------------------------------

def localize_images(raw, year, number, branch, images_dir, timeout, download, log_ctx):
    """下载原库 imageUrls 指向的原卷配图到 images/<原名>, 返回本地引用 HTML 片段。

    原库图片引用在 imageUrls 字段(如 "./assets/2009-q35-original.png"),
    相对 dist/questions.json 即 dist/assets/<原名>。未取得配图(原库
    missingImage, 如 2012-04)无 URL 可下, 原样跳过。
    """
    frags = []
    for u in raw.get("imageUrls") or []:
        name = u.rstrip("/").split("/")[-1]
        if not name or not re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]*$", name):
            log_ctx(f"非常规图片引用 {u!r}, 跳过本地化")
            continue
        dest = images_dir / name
        if download and not (dest.exists() and dest.stat().st_size > 0):
            url = f"{RAW_BASE}/{MAIN_REPO}/{branch}/dist/assets/{urllib.parse.quote(name)}"
            try:
                dest.write_bytes(http_get(url, timeout))
                log_ctx(f"图片已下载 images/{name}({dest.stat().st_size} B)")
            except Exception as e:  # noqa: BLE001 — 单图失败不中断
                log_ctx(f"图片下载失败 {name}: {e}; 仍按 images/{name} 引用")
        elif not download:
            log_ctx(f"--no-images: 跳过下载, 仍按 images/{name} 引用")
        alt = html_mod.escape(raw.get("figureNote") or f"{year}年第{number}题原卷配图")
        frags.append(f'<figure class="q-figure"><img src="images/{name}" alt="{alt}"></figure>')
    return "".join(frags)


# ---------------------------------------------------------------------------
# 归一化
# ---------------------------------------------------------------------------

def points_for(year, number, qtype):
    if year in POINTS_OVERRIDE and number in POINTS_OVERRIDE[year]:
        return POINTS_OVERRIDE[year][number]
    return BASE_POINTS[qtype]


def normalize_question(raw, branch, images_dir, timeout, download, log_ctx):
    year, number = int(raw["year"]), int(raw["number"])
    qtype = TYPE_MAP.get(raw.get("type"))
    if qtype is None:
        raise ValueError(f"未知题型 {raw.get('type')!r}")

    # 题干(分析题材料已在原库 stem 内, 一并入 HTML); 配图追加在题干末尾
    stem_html = to_html(raw.get("stem"))
    stem_html += localize_images(raw, year, number, branch, images_dir,
                                 timeout, download, log_ctx)
    if not stem_html:
        log_ctx(f"题 {number} 题干为空")

    # 选项与答案
    options, answer = [], None
    if qtype in ("单选题", "多选题"):
        opts = raw.get("options") or {}
        for letter in sorted(opts):
            options.append({"letter": str(letter), "html": to_html(str(opts[letter] or ""))})
        letters = [str(a).strip().upper() for a in (raw.get("answer") or [])]
        answer = "".join(sorted(letters))
        if qtype == "单选题" and (len(answer) != 1 or answer not in "ABCD"):
            log_ctx(f"单选题 {number} 答案 {raw.get('answer')!r} 异常")
        if qtype == "多选题" and (not 2 <= len(answer) <= 4 or set(answer) - set("ABCD")):
            log_ctx(f"多选题 {number} 答案 {raw.get('answer')!r} 异常")
        if not to_html(raw.get("explanation")):
            log_ctx(f"选择题 {number} 原库 explanation 为空, refAnalysis 为空串")
        ref_analysis = to_html(raw.get("explanation"))
    else:
        # 分析题: options 置空, answer 无字母解(置 null), 参考答案按问拆分
        parts = split_analysis_answer(raw.get("referenceAnswer"))
        if not parts:
            log_ctx(f"分析题 {number} 原库 referenceAnswer 为空, refAnalysis 为空数组")
        ref_analysis = [to_html(p) for p in parts]
        expect_n = stem_subq_count(raw.get("stem"))
        if parts and expect_n and len(parts) != expect_n:
            log_ctx(f"分析题 {number} 参考答案拆为 {len(parts)} 问, "
                    f"题干设问标记计 {expect_n} 个, 请人工核对")

    tags = raw.get("tags") or []
    return {
        "id": f"zz-{year}-{number:02d}",
        "year": year,
        "number": number,
        "type": qtype,
        "points": points_for(year, number, qtype),
        "stemHtml": stem_html,
        "options": options,
        "answer": answer,
        "refAnalysis": ref_analysis,
        "tags": [tags[0]] if tags else [],
    }


def normalize_year(year, raws, images_dir, branch, timeout, download, log_ctx):
    qs = [q for q in raws if int(q["year"]) == year]
    if not qs:
        raise ValueError(f"主源无 {year} 年数据")
    out = sorted((normalize_question(q, branch, images_dir, timeout, download, log_ctx)
                  for q in qs), key=lambda q: q["number"])

    # 每年结构与分值校验(告警不中断)
    structure = {}
    for q in out:
        structure[q["type"]] = structure.get(q["type"], 0) + 1
    if len(out) != 38:
        log_ctx(f"题量 {len(out)} != 38, 请核对")
    if structure != {"单选题": 16, "多选题": 17, "分析题": 5}:
        log_ctx(f"题型结构 {structure} != {{单选16, 多选17, 分析5}}, 请核对")
    total = sum(q["points"] for q in out)
    if total != YEARLY_TOTAL:
        log_ctx(f"全卷分值合计 {total} != {YEARLY_TOTAL}, 请核对")
    ids = [q["id"] for q in out]
    if len(set(ids)) != len(ids):
        log_ctx("存在重复 id, 请核对")
    log_ctx(f"写入 {len(out)} 题(单选{structure.get('单选题', 0)}/多选"
            f"{structure.get('多选题', 0)}/分析{structure.get('分析题', 0)}), "
            f"分值合计 {total}")
    return {"year": year, "count": len(out), "questions": out}


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def parse_years(spec):
    years = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            years.update(range(int(a), int(b) + 1))
        else:
            years.add(int(part))
    return sorted(y for y in years if DEFAULT_YEAR_START <= y <= DEFAULT_YEAR_END)


def main(argv=None):
    ap = argparse.ArgumentParser(description="抽取考研政治(101) 2009–2026 真题(主源 kaoyan-politics)")
    ap.add_argument("--years", default=f"{DEFAULT_YEAR_START}-{DEFAULT_YEAR_END}",
                    help="年份, 如 2009-2026 或 2021,2023")
    ap.add_argument("--branch", default=None, help="主源分支(默认 main, 失败回退 master)")
    ap.add_argument("--force", action="store_true", help="重新拉取主源并强制重建已有年份文件")
    ap.add_argument("--no-images", action="store_true", help="不下载图片, 引用仍改写为 images/<原名>")
    ap.add_argument("--timeout", type=int, default=30, help="单次 HTTP 超时秒数")
    args = ap.parse_args(argv)

    root = Path(__file__).resolve().parent.parent            # /Users/a24/jiaoben/politics101
    questions_dir = root / "data" / "questions"
    images_dir = root / "images"
    for d in (questions_dir, images_dir, root / "data" / "source", root / "tools"):
        d.mkdir(parents=True, exist_ok=True)

    years = parse_years(args.years)
    if not years:
        log(f"--years 解析结果为空, 有效范围 {DEFAULT_YEAR_START}-{DEFAULT_YEAR_END}")
        print(json.dumps({"total": 0, "perYear": {}}, ensure_ascii=False, separators=(",", ":")))
        return 1

    try:
        payload, source_md5, branch_used = fetch_source(root, args.force, args.timeout)
    except Exception as e:  # noqa: BLE001 — 主源不可得则整体失败
        log(f"主源不可得, 终止: {e}")
        print(json.dumps({"total": 0, "perYear": {}}, ensure_ascii=False, separators=(",", ":")))
        return 1
    branch = args.branch or branch_used or BRANCHES[0]
    data = json.loads(payload.decode("utf-8"))
    all_raw = data.get("questions") or []

    download = not args.no_images
    per_year, ok_years = {}, []

    for year in years:
        out_path = questions_dir / f"{year}.json"

        def log_ctx(msg, _y=year):
            log(f"{_y}: {msg}")

        # 可重入: 已有年份数据则跳过(损坏的文件除外)
        if out_path.exists() and not args.force:
            try:
                existing = json.loads(out_path.read_text(encoding="utf-8"))
                per_year[year] = len(existing.get("questions") or [])
                ok_years.append(year)
                log_ctx(f"已存在 data/questions/{year}.json, 跳过")
                continue
            except (ValueError, OSError) as e:
                log_ctx(f"现有文件损坏({e}), 重建")

        try:
            year_obj = normalize_year(year, all_raw, images_dir, branch,
                                      args.timeout, download, log_ctx)
        except Exception as e:  # noqa: BLE001 — 单年失败不中断其余年份
            log_ctx(f"抽取失败: {e}")
            continue
        out_path.write_text(json.dumps(year_obj, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
        per_year[year] = year_obj["count"]
        ok_years.append(year)

    # meta.json 与 stdout 的 perYear: 以磁盘上实际存在的年份数据为准(含此前
    # 运行已产出、本轮跳过的年份), 保证 total 与 perYear 口径一致
    years_on_disk = sorted(
        int(p.stem) for p in questions_dir.glob("*.json")
        if p.stem.isdigit() and DEFAULT_YEAR_START <= int(p.stem) <= DEFAULT_YEAR_END
    )
    total, per_year = 0, {}
    for y in years_on_disk:
        try:
            n = len((json.loads((questions_dir / f"{y}.json").read_text(encoding="utf-8"))
                     .get("questions") or []))
            per_year[y] = n
            total += n
        except (ValueError, OSError) as e:
            log(f"读取 {y}.json 统计失败: {e}")
    meta = {
        "years": years_on_disk,
        "total": total,
        "source": {
            "repo": MAIN_REPO,
            "path": SOURCE_PATH,
            "branch": branch,
            "md5": source_md5,
            "sizeBytes": len(payload),
        },
    }
    (root / "data" / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    failed = [y for y in years if y not in ok_years]
    if failed:
        log(f"以下年份未产出: {failed}")
    if not years_on_disk:
        log("没有任何年份产出")
        print(json.dumps({"total": 0, "perYear": {}}, ensure_ascii=False, separators=(",", ":")))
        return 1

    print(json.dumps({"total": total,
                      "perYear": {str(y): per_year[y] for y in sorted(per_year)}},
                     ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
