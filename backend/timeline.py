#!/usr/bin/env python3
"""
往事可追忆 · 时间轴提取算法（原型 v0.1）

=== 依据：需求书 v2.4 第四节 3️⃣（全项目最难，建议优先立独立攻坚项目）===

三类线索：
  ① 显式年代   "1968年" "七几年" "1979年3月"
  ② 历史事件   "文革那会儿" "分田到户那年" "开放高考那年"
  ③ 人生锚点   "我八岁那年" "嫁过来第二年" → 用已知年份反推

=== 铁律（v2.4，逐字执行，绝不打折扣）===
  1. 无法判定时标「时间待定」，**不瞎猜、不归错位**
  2. 模糊表述**原样保留**：老人说"七几年" → 记成「1970年代（老人说的）」
     **绝不许凑整成"1975年3月"**
  3. 精度不影响排序
  4. 一旦采到锚点，后续同类表述可自动换算
  5. 保存即触发排序调整

=== 设计原则 ===
- 只输出**有把握**的结果；把握不足一律 UNKNOWN
- 所有判断都带 evidence（命中的原文片段），便于人工复核与回溯
- 纯标准库实现，不引外部依赖（本机 numpy/sklearn 环境不稳）
"""

from __future__ import annotations

import re
import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional


# ============================================================
# 枚举与数据结构
# ============================================================

class Precision(str, Enum):
    YEAR = "year"
    SEASON = "season"
    MONTH = "month"
    DAY = "day"
    FUZZY = "fuzzy"       # 只知道大概，如"七几年"
    UNKNOWN = "unknown"   # 时间待定


class Method(str, Enum):
    EXPLICIT_YEAR = "显式年代"
    HISTORY_EVENT = "历史事件"
    LIFE_ANCHOR = "人生锚点"
    FUZZY_DECADE = "模糊年代"
    UNKNOWN = "待定"


@dataclass
class TimeResult:
    """一条时间提取结果"""
    raw: str = ""                     # 原样保留的表述
    label: str = ""                   # 展示用（模糊的带"（老人说的）"）
    precision: str = Precision.UNKNOWN.value
    sort_key: Optional[int] = None    # 排序键（年）
    start_year: Optional[int] = None
    end_year: Optional[int] = None
    month: Optional[int] = None
    day: Optional[int] = None
    method: str = Method.UNKNOWN.value
    evidence: str = ""                # 命中的原文片段（便于复核）
    confidence: float = 0.0           # 0-1
    note: str = ""                    # 附注（如"由锚点推算"）

    def to_dict(self):
        return asdict(self)


# ============================================================
# 语料库：三类线索
# ============================================================

# --- ① 历史事件锚点（中国近现代，老人常挂嘴边的）---
# 值 = (基准年, 说明)。区间类给范围。
HISTORY_EVENTS = {
    "解放前": (None, None, "1949", "解放前（1949年前）"),
    "解放后": (1949, 1949, "1949", "解放后（1949年后）"),
    "建国那会": (1949, 1949, "1949", "建国那会儿（1949）"),
    "建国初期": (1949, 1952, "1949", "建国初期"),
    "抗美援朝": (1950, 1953, "1950", "抗美援朝（1950-1953）"),
    "土改": (1950, 1952, "1950", "土改（1950-1952）"),
    "公社那会儿": (1958, 1984, "1958", "人民公社时期（1958-1984）"),
    "大炼钢铁": (1958, 1958, "1958", "大炼钢铁（1958）"),
    "三年困难": (1959, 1961, "1959", "三年困难时期（1959-1961）"),
    "困难时期": (1959, 1961, "1959", "三年困难时期（1959-1961）"),
    "文革": (1966, 1976, "1966", "文革（1966-1976）"),
    "文化大革命": (1966, 1976, "1966", "文革（1966-1976）"),
    "上山下乡": (1968, 1978, "1968", "上山下乡（1968-1978）"),
    "插队": (1968, 1978, "1968", "插队（1968-1978）"),
    "恢复高考": (1977, 1977, "1977", "恢复高考（1977）"),
    "分田到户": (1978, 1984, "1978", "分田到户（1978起）"),
    "包产到户": (1978, 1984, "1978", "包产到户（1978起）"),
    "改革开放": (1978, 1978, "1978", "改革开放（1978）"),
    "下海": (1984, 1995, "1984", "下海经商（1984起）"),
    "下岗": (1995, 2000, "1995", "下岗潮（1995-2000）"),
    "非典": (2003, 2003, "2003", "非典（2003）"),
    "汶川": (2008, 2008, "2008", "汶川地震（2008）"),
    "新冠": (2020, 2022, "2020", "新冠（2020-2022）"),
}

# --- ③ 人生锚点表述模板 ---
# "我X岁那年" / "X岁那年" / "嫁过来第N年" / "结婚第N年" / "生老大那年"
RE_AGE_YEAR = re.compile(r"(?:我|俺|自己)?\s*(\d{1,2}|[一二三四五六七八九十]{1,3})\s*岁(?:那|的)?(?:一)?年")
RE_MARRIAGE_N = re.compile(r"(?:嫁过来|结婚|过门)(?:的)?第\s*(\d{1,2}|[一二三四五六七八九十]{1,3})\s*年")
RE_MOVE_N = re.compile(r"(?:搬|迁)(?:到|来)(?:这|那)?(?:儿|里)?(?:的)?第\s*(\d{1,2})\s*年")
RE_CHILD_YEAR = re.compile(r"(?:生|有)(?:了)?(?:大|二|三|老)(?:儿子|闺女|娃|女儿|小子)那年")

# 锚点类型
ANCHOR_AGE = "age"                  # 当时几岁（须配出生年）
ANCHOR_MARRIAGE = "marriage"        # 结婚年份（须配结婚年）
ANCHOR_CHILD_BIRTH = "child_birth"  # 老大出生年

# --- ① 显式年代 ---
RE_YEAR_FULL = re.compile(r"(1[89]\d{2}|20[0-2]\d)\s*年")
RE_YEAR_MONTH = re.compile(r"(1[89]\d{2}|20[0-2]\d)\s*年\s*(\d{1,2}|[一二三四五六七八九十]{1,3})\s*月")
RE_YEAR_SEASON = re.compile(r"(1[89]\d{2}|20[0-2]\d)\s*年\s*(春|夏|秋|冬)(?:天)?")
RE_YEAR_MONTH_DAY = re.compile(
    r"(1[89]\d{2}|20[0-2]\d)\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]"
)

# 十年代模糊："七几年" "七零年" "70年代" "七十年代" "七十年代初/末"
CN_NUM = {'零': 0, '一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
          '六': 6, '七': 7, '八': 8, '九': 9}
RE_DECADE_CN = re.compile(r"([一二三四五六七八九])十年代|([一二三四五六七八九])几年|([一二三四五六七八九])零年")
RE_DECADE_ARAB = re.compile(r"((?:19|20)?[0-9])0\s*年代")
RE_DECADE_WORD = re.compile(r"(五十|六十|七十|八十|九十|五十|六十)年代")

# 早于/晚于
RE_BEFORE = re.compile(r"(解放前|[0-9]{2,4}年?(?:以)?前)")
RE_AFTER = re.compile(r"([0-9]{2,4}年?(?:以)?后|之后)")


# ============================================================
# 工具
# ============================================================

def _cn2int(s: str) -> Optional[int]:
    """中文数字转 int（支持 '八' '十八' '二十三'）"""
    s = s.strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    if s == "十":
        return 10
    if "十" in s:
        parts = s.split("十")
        tens = CN_NUM.get(parts[0], 1) if parts[0] else 1
        ones = CN_NUM.get(parts[1], 0) if len(parts) > 1 and parts[1] else 0
        return tens * 10 + ones
    if len(s) == 1 and s in CN_NUM:
        return CN_NUM[s]
    # 多位：逐字
    try:
        return int(''.join(str(CN_NUM[c]) for c in s))
    except Exception:
        return None


def _decade_cn_to_year(ch: str) -> Optional[int]:
    """'七' → 1970（老人多指 19xx；若语境未来可另判）"""
    n = CN_NUM.get(ch)
    if n is None:
        return None
    return 1900 + n * 10


# ============================================================
# 主提取函数
# ============================================================

def extract_time(text: str, anchors: Optional[dict] = None) -> TimeResult:
    """
    从一段文本提取时间。

    anchors: 已知人生锚点，如 {'birth_year': 1950, 'marriage_year': 1972,
                               'child_birth_year': 1975}
    返回 TimeResult。**判定不了就返回 UNKNOWN，不猜。**
    """
    if not text or not text.strip():
        return TimeResult(raw=text or "", method=Method.UNKNOWN.value,
                          note="空文本，时间待定")

    anchors = anchors or {}
    t = text.strip()

    # ---- 优先级 1：完整年月日 / 年月 / 年季 / 年（最确定）----
    m = RE_YEAR_MONTH_DAY.search(t)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return TimeResult(
            raw=m.group(0), label=f"{y}年{mo}月{d}日",
            precision=Precision.DAY.value, sort_key=y, start_year=y, end_year=y,
            month=mo, day=d, method=Method.EXPLICIT_YEAR.value,
            evidence=m.group(0), confidence=0.98,
        )

    m = RE_YEAR_MONTH.search(t)
    if m:
        y = int(m.group(1))
        mo = _cn2int(m.group(2))
        if mo and 1 <= mo <= 12:
            return TimeResult(
                raw=m.group(0), label=f"{y}年{mo}月",
                precision=Precision.MONTH.value, sort_key=y, start_year=y, end_year=y,
                month=mo, method=Method.EXPLICIT_YEAR.value,
                evidence=m.group(0), confidence=0.97,
            )

    m = RE_YEAR_SEASON.search(t)
    if m:
        y, season = int(m.group(1)), m.group(2)
        season_map = {'春': (3, 5), '夏': (6, 8), '秋': (9, 11), '冬': (12, 2)}
        return TimeResult(
            raw=m.group(0), label=f"{y}年{season}",
            precision=Precision.SEASON.value, sort_key=y, start_year=y, end_year=y,
            method=Method.EXPLICIT_YEAR.value,
            evidence=m.group(0), confidence=0.95,
            note=f"季节 {season}",
        )

    m = RE_YEAR_FULL.search(t)
    if m:
        y = int(m.group(1))
        # 排除"1970年代"被误当成"1970年"
        if "年代" not in t[max(0, m.start() - 1):m.end() + 3]:
            return TimeResult(
                raw=m.group(0), label=f"{y}年",
                precision=Precision.YEAR.value, sort_key=y, start_year=y, end_year=y,
                method=Method.EXPLICIT_YEAR.value,
                evidence=m.group(0), confidence=0.95,
            )

    # ---- 优先级 2：模糊年代（**原样保留，绝不凑整**）----
    m = RE_DECADE_CN.search(t)
    if m:
        ch = m.group(1) or m.group(2) or m.group(3)
        y = _decade_cn_to_year(ch)
        if y:
            raw = m.group(0)
            # 铁律：记成「1970年代（老人说的）」
            return TimeResult(
                raw=raw, label=f"{y}年代（老人说的）",
                precision=Precision.FUZZY.value, sort_key=y,
                start_year=y, end_year=y + 9,
                method=Method.FUZZY_DECADE.value,
                evidence=raw, confidence=0.85,
                note="模糊表述，原样保留，未凑整到具体年月",
            )

    m = RE_DECADE_ARAB.search(t)
    if m:
        p = m.group(1)
        y = int(p) * 10 if len(p) <= 2 else int(p)
        if y < 1000:
            y = 1900 + y
        raw = m.group(0)
        return TimeResult(
            raw=raw, label=f"{y}年代（老人说的）",
            precision=Precision.FUZZY.value, sort_key=y,
            start_year=y, end_year=y + 9,
            method=Method.FUZZY_DECADE.value,
            evidence=raw, confidence=0.85,
            note="模糊表述，原样保留",
        )

    # ---- 优先级 3：人生锚点（须有 anchors 才能算，否则待定）----
    m = RE_AGE_YEAR.search(t)
    if m:
        age = _cn2int(m.group(1))
        birth = anchors.get('birth_year')
        if age is not None and birth:
            y = birth + age
            return TimeResult(
                raw=m.group(0), label=f"{y}年（老人说的「{age}岁那年」）",
                precision=Precision.YEAR.value, sort_key=y, start_year=y, end_year=y,
                method=Method.LIFE_ANCHOR.value,
                evidence=m.group(0), confidence=0.9,
                note=f"由出生年 {birth} + {age} 岁推算",
            )
        return TimeResult(
            raw=m.group(0), label=f"老人说的「{age}岁那年」",
            precision=Precision.FUZZY.value, sort_key=None,
            method=Method.LIFE_ANCHOR.value,
            evidence=m.group(0), confidence=0.4,
            note=f"⚠️ 缺出生年锚点，无法换算 → 时间待定（不猜）",
        )

    m = RE_MARRIAGE_N.search(t)
    if m:
        n = _cn2int(m.group(1))
        my = anchors.get('marriage_year')
        if n is not None and my:
            y = my + n - 1
            return TimeResult(
                raw=m.group(0), label=f"{y}年（老人说的「结婚第{n}年」）",
                precision=Precision.YEAR.value, sort_key=y, start_year=y, end_year=y,
                method=Method.LIFE_ANCHOR.value,
                evidence=m.group(0), confidence=0.88,
                note=f"由结婚年 {my} 推算",
            )
        return TimeResult(
            raw=m.group(0), label=f"老人说的「结婚第{n}年」",
            precision=Precision.FUZZY.value,
            method=Method.LIFE_ANCHOR.value,
            evidence=m.group(0), confidence=0.4,
            note="⚠️ 缺结婚年锚点，无法换算 → 时间待定（不猜）",
        )

    if RE_CHILD_YEAR.search(t):
        cb = anchors.get('child_birth_year')
        if cb:
            return TimeResult(
                raw=RE_CHILD_YEAR.search(t).group(0),
                label=f"{cb}年（老大出生那年）",
                precision=Precision.YEAR.value, sort_key=cb,
                start_year=cb, end_year=cb,
                method=Method.LIFE_ANCHOR.value,
                evidence=RE_CHILD_YEAR.search(t).group(0), confidence=0.88,
                note=f"由老大出生年 {cb} 推算",
            )
        return TimeResult(
            raw=RE_CHILD_YEAR.search(t).group(0), label="老大出生那年",
            precision=Precision.FUZZY.value,
            method=Method.LIFE_ANCHOR.value,
            evidence=RE_CHILD_YEAR.search(t).group(0), confidence=0.4,
            note="⚠️ 缺老大出生年锚点 → 时间待定（不猜）",
        )

    # ---- 优先级 4：历史事件（给范围，标 FUZZY）----
    for kw, (sy, ey, sort_y, label) in HISTORY_EVENTS.items():
        if kw in t:
            return TimeResult(
                raw=kw, label=f"{label}（老人说的）",
                precision=Precision.FUZZY.value,
                sort_key=int(sort_y),
                start_year=sy, end_year=ey,
                method=Method.HISTORY_EVENT.value,
                evidence=kw, confidence=0.8,
                note="由历史事件推区间；具体年份须老人确认",
            )

    # ---- 优先级 5：判定不了 → 时间待定（**不瞎猜**）----
    return TimeResult(
        raw=t[:40], label="时间待定",
        precision=Precision.UNKNOWN.value, sort_key=None,
        method=Method.UNKNOWN.value,
        evidence="", confidence=0.0,
        note="未命中任何时间线索 → 标「时间待定」，不猜不归错位",
    )


# ============================================================
# 锚点抽取（从已有故事里自动采锚点）
# ============================================================

RE_BIRTH = re.compile(r"(?:我|俺)?\s*(1[89]\d{2}|20[0-2]\d)\s*年\s*(?:出生|生的)")
RE_MARRIAGE_Y = re.compile(r"(?:我|俺)?\s*(1[89]\d{2}|20[0-2]\d)\s*年\s*(?:结的婚|嫁|结婚)")
RE_CHILD_BIRTH_Y = re.compile(r"(1[89]\d{2}|20[0-2]\d)\s*年\s*(?:生|有)了?(?:大|二|三|老)(?:儿子|闺女|娃|女儿|小子)")


def extract_anchors(text: str) -> dict:
    """从文本里采集人生锚点，返回 {'birth_year':.., 'marriage_year':..}"""
    out = {}
    m = RE_BIRTH.search(text)
    if m:
        out['birth_year'] = int(m.group(1))
    m = RE_MARRIAGE_Y.search(text)
    if m:
        out['marriage_year'] = int(m.group(1))
    m = RE_CHILD_BIRTH_Y.search(text)
    if m:
        out['child_birth_year'] = int(m.group(1))
    return out


# ============================================================
# 排序（精度不影响排序；无法判定排最后）
# ============================================================

def sort_stories(results: list) -> list:
    """
    按时间排序。**无法判定的排最后，但不丢弃**（v2.4：不归错位）。
    """
    def keyf(r: TimeResult):
        if r.sort_key is None:
            return (1, 0)          # 待定 → 排最后
        return (0, r.sort_key)
    return sorted(results, key=keyf)


# ============================================================
# 自测
# ============================================================

if __name__ == '__main__':
    print("=" * 62)
    print("往事可追忆 · 时间轴提取算法 · 自测")
    print("=" * 62)

    anchors = {'birth_year': 1950, 'marriage_year': 1972, 'child_birth_year': 1975}

    cases = [
        ("1979年3月5日那天", anchors),
        ("1979年3月", anchors),
        ("1979年春天", anchors),
        ("1979年", anchors),
        ("七几年那场大水", anchors),
        ("文革那会儿", anchors),
        ("分田到户那年", anchors),
        ("我八岁那年", anchors),
        ("嫁过来第二年", anchors),
        ("生老大那年", anchors),
        ("我八岁那年", {}),                 # 缺锚点 → 待定
        ("那年水来得快，家里东西都漂走了", anchors),  # 无线索 → 待定
    ]

    results = []
    for txt, anc in cases:
        r = extract_time(txt, anc)
        results.append(r)
        tag = "✅" if r.sort_key is not None else "⏸"
        print(f"\n{tag} 原文: {txt}")
        print(f"   展示: {r.label}")
        print(f"   精度: {r.precision:<8} 排序键: {str(r.sort_key):<6} 手法: {r.method}")
        print(f"   把握: {r.confidence}  {('附注: ' + r.note) if r.note else ''}")

    print("\n" + "=" * 62)
    print("排序验证（待定的排最后，不丢弃）:")
    print("=" * 62)
    for r in sort_stories(results):
        print(f"  {str(r.sort_key):<6} {r.label}")

    print("\n" + "=" * 62)
    print("锚点抽取验证:")
    print("=" * 62)
    for t in ["我1950年出生的", "1972年结的婚", "1975年生了老大"]:
        print(f"  {t}  →  {extract_anchors(t)}")
