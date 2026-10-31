"""
往事可追忆 · 采访「听懂」层（llm_brain）v1.0
建立：2026-10-31（sandy 真机验收后定死：采访必须是「有声 + 能听懂 + 会接话」）

=== 为什么要这一层 ===
原来的 api_next_question 是「按锚点题库顺次跳」：不管老人上一句说了什么，
下一句永远是题库里的下一个。sandy 原话：「问题按预置题库顺次跳、不跟老人上一句走」。
这不是采访，是问卷。

本层补的是：**老人说了一句 → 先读懂这句 → 由这句决定下一句问什么。**

=== 设计口径（三条铁律）===
1. **必须接得住**：下一问里要带上老人刚才说过的具体词（人名/地名/年份/物件），
   让老人听到「它在跟我聊」，不是「它在念下一题」。
2. **允许跑题**：老人想说别的就顺着走（follow_digression=True），不硬拉回题库。
3. **永不断线**：模型超时/出错/没配密钥 → **必回一句能问出口的话**（降级到锚点题库），
   绝不返回空、绝不让前端卡住。老人面前不能出现「AI 出错了」。

=== 顺带做两件事 ===
- `extract_anchor_year`：从老人这句话里抓年份（"我1958年生的"→1958），交给 anchor_api 落锚点。
  这一步是免费的（正则），抓不到就返回 None，不调模型。
- `recap_line`：每聊 N 段给老人回一句「您刚才说的我记下了」——让老人知道自己在被听见。

=== 依赖 ===
DeepSeek（密钥在 ~/.hermes/.env 的 DEEPSEEK_API_KEY）。
无第三方 SDK，用 requests 直调 /chat/completions，零安装。
"""

import json
import os
import re
import sys
import time
from pathlib import Path


# ============================================================
# 一、模型配置（可被环境变量覆盖，默认 DeepSeek）
# ============================================================

LLM_BASE = os.environ.get("ECHOES_LLM_BASE", "https://api.deepseek.com/v1").rstrip("/")
LLM_MODEL = os.environ.get("ECHOES_LLM_MODEL", "deepseek-chat")
LLM_TIMEOUT = float(os.environ.get("ECHOES_LLM_TIMEOUT", "12"))   # 老人等不了太久
LLM_MAX_TOKENS = 220

_ENV_CANDIDATES = [
    Path.home() / ".hermes" / ".env",
    Path.home() / ".config" / "yuanekang" / "echoes_llm.json",
    Path.home() / "echoes" / "config" / "secrets" / "echoes_llm.json",
]


def load_llm_key() -> str:
    """读模型密钥。顺序：环境变量 → ~/.hermes/.env → config/secrets。"""
    k = os.environ.get("ECHOES_LLM_API_KEY", "").strip()
    if k:
        return k
    k = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if k:
        return k

    for p in _ENV_CANDIDATES:
        if not p.exists():
            continue
        try:
            raw = p.read_text(encoding="utf-8").strip()
        except Exception:
            continue
        if p.suffix == ".json":
            try:
                d = json.loads(raw)
                v = str(d.get("api_key", "")).strip()
                if v:
                    return v
            except Exception:
                pass
            continue
        for line in raw.splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            name, _, val = line.partition("=")
            if name.strip() in ("DEEPSEEK_API_KEY", "ECHOES_LLM_API_KEY"):
                v = val.strip().strip('"').strip("'")
                if v:
                    return v
    return ""


def llm_available() -> bool:
    return bool(load_llm_key())


# ============================================================
# 二、调模型（任何失败都不抛，返回 ("", 原因)）
# ============================================================

def _chat(messages, *, temperature: float = 0.7, max_tokens: int = LLM_MAX_TOKENS):
    """
    返回 (文本, 失败原因)。失败时 文本为空字符串，原因是一句中文（写日志用，不给老人看）。
    """
    key = load_llm_key()
    if not key:
        return "", "未配置模型密钥"

    try:
        import requests
    except ImportError as e:
        return "", f"缺 requests：{e}"

    payload = {
        "model": LLM_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    try:
        r = requests.post(
            f"{LLM_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json"},
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            timeout=LLM_TIMEOUT,
        )
        if r.status_code != 200:
            return "", f"模型返回 HTTP {r.status_code}：{r.text[:200]}"
        d = r.json()
        text = (d.get("choices") or [{}])[0].get("message", {}).get("content", "")
        return (text or "").strip(), ""
    except Exception as e:
        return "", f"调用模型出错：{type(e).__name__}: {e}"


# ============================================================
# 三、抓年份（免费，纯正则，不调模型）
# ============================================================

# 中文年份：一九五八 / 五八年 / 58年 / 1958
_CN_DIGIT = {"零": 0, "〇": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
             "六": 6, "七": 7, "八": 8, "九": 9,
             "两": 2, "十": 10}


def _cn_num(s: str):
    """把中文数字串转成 int：一九五八 → 1958；五十八 → 58。认不出返回 None。"""
    s = (s or "").strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    # 逐字（年份读法）：一九五八
    if all(ch in _CN_DIGIT for ch in s) and "十" not in s:
        return int("".join(str(_CN_DIGIT[ch]) for ch in s))
    return None


def extract_anchor_year(text: str):
    """
    从一句话里抓「年份」。抓不到返回 None。

    覆盖常见老人说法：
      1958年 / 一九五八年 / 五八年 / 58年 / 我今年七十了（不算年份，不算）
    只认 1930-2020 区间（更早更晚基本是误抓，如门牌号）。
    """
    t = (text or "").strip()
    if not t:
        return None

    # ① 四位阿拉伯年份 + 可选「年」
    for m in re.finditer(r"(19[3-9]\d|20[0-1]\d)\s*年?", t):
        y = int(m.group(1))
        if 1930 <= y <= 2020:
            return y

    # ② 四位中文年份：一九五八年
    m = re.search(r"([零〇一二三四五六七八九]{4})\s*年", t)
    if m:
        y = _cn_num(m.group(1))
        if y and 1930 <= y <= 2020:
            return y

    # ③ 两位简说：五八年 / 58年 / 九八年（有「年」字才算，避免误抓数量）
    m = re.search(r"([零〇一二三四五六七八九]{2}|[3-9]\d)\s*年", t)
    if m:
        y = _cn_num(m.group(1))
        if y is not None:
            full = 1900 + y if y >= 30 else 2000 + y
            if 1930 <= full <= 2020:
                return full
    return None


# ============================================================
# 四、采访人格（给模型的系统提示）
# ============================================================

SYSTEM_PROMPT = """你是一位陪老人聊天的晚辈，专门帮老人把一辈子的经历慢慢讲出来，记成一本家书。

规矩（必须遵守）：
1. 你只问一句话，不超过 30 个字。老人在打电话，听不清长句子。
2. **必须接住老人上一句里说过的具体东西**（地名、人名、年份、物件、动作），
   在问题里带上它，让老人觉得你真的在听。
   例：老人说「我小时候在山东农村，家里种地」→ 你问「山东那个村子，小时候您也下地吗？」
   反例：「您小时候住在哪里？」——无视老人刚说的话，绝对不许这样问。
3. 老人跑题就顺着走，别硬拉回来。老人说到孙子就聊孙子。
4. 用老人的话，别用书面语。不说「请问」「是否」「您能描述一下」。
5. 一次只问一个事，别一次问两三个。
6. 如果老人这句里有具体年份，可以在下一问里用上（「五八年那会儿您多大？」）。
7. 绝不评价、绝不总结、绝不说「我理解您的感受」这类套话。
8. 只输出问题本身，不要任何前缀、不要引号、不要解释。

如果老人这句话是「嗯/对/好/不知道/没听清」这类没内容的，就问一个具体的小事，
别重复刚才的问法。"""


# ============================================================
# 五、核心：由老人这一句，决定下一句
# ============================================================

def next_question_from_answer(
    *,
    answer_text: str,
    asked_question: str = "",
    history: list = None,
    anchor_hint: str = "",
    owner_birth_year=None,
) -> dict:
    """
    老人答完一句 → 生成下一问。

    入参：
      answer_text   老人刚说的（**转写后的文字**，可从 ASR 拿到）
      asked_question 上一句问了什么（让模型知道别重复）
      history       最近几轮 [(问, 答), ...]，可为空
      anchor_hint   题库里还缺的锚点方向（如 "还没问到哪年结婚"），降级时用
      owner_birth_year 老人出生年（算年龄用）

    返回统一形状（**永远 ok，永远有 question**）：
      {
        "question": "您说的是山东那个村，那时候家里也种地吗？",
        "kind": "llm" | "fallback",
        "heard": "老人这句转写原文",
        "years": [1958],          # 抓到的时间
        "degraded_reason": "",    # 非空=降级了（写日志，不给前端显示）
      }
    """
    heard = (answer_text or "").strip()
    years = [y for y in [extract_anchor_year(heard)] if y]

    # ---- 老人这句没内容 → 不浪费模型调用，直接给具体的小事问 ----
    if not heard or _is_contentless(heard):
        q = _echo_probe(heard)
        return {
            "question": q,
            "kind": "fallback",
            "heard": heard,
            "years": years,
            "degraded_reason": "老人这句没有内容，走了具体小事问",
        }

    # ---- 正常：让模型读这句再问 ----
    if llm_available():
        msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
        if owner_birth_year:
            msgs.append({"role": "system",
                         "content": f"老人是 {owner_birth_year} 年出生的。"})
        for (q0, a0) in (history or [])[-4:]:
            if q0:
                msgs.append({"role": "assistant", "content": q0})
            if a0:
                msgs.append({"role": "user", "content": a0})
        if asked_question:
            msgs.append({"role": "assistant", "content": asked_question})
        msgs.append({"role": "user", "content": heard})

        raw, why = _chat(msgs, temperature=0.75)
        q = _clean_question(raw)
        if q:
            return {"question": q, "kind": "llm", "heard": heard,
                    "years": years, "degraded_reason": ""}
        degraded = why or "模型没给出可用的话"
    else:
        degraded = "未配置模型密钥"

    # ---- 降级：绝不空手 ----
    return {
        "question": _fallback_question(heard, anchor_hint=anchor_hint,
                                       birth_year=owner_birth_year),
        "kind": "fallback",
        "heard": heard,
        "years": years,
        "degraded_reason": degraded,
    }


# ============================================================
# 六、降级与清洗（这些是「永不空手」的保险）
# ============================================================

_NOISE = {"嗯", "对", "好", "行", "中", "是", "嗯嗯", "对对", "啊", "哦",
          "不知道", "不记得", "忘了", "没听清", "什么", "啥", "再说一遍",
          "随便", "都行"}


def _is_contentless(text: str) -> bool:
    t = re.sub(r"[\s，。,.!！?？~、]", "", text or "")
    return (not t) or (t in _NOISE) or (len(t) <= 2)


def _clean_question(raw: str) -> str:
    """把模型输出洗成一句能直接念的话。不像话就返回空（触发降级）。"""
    q = (raw or "").strip()
    if not q:
        return ""
    # 去掉常见的模型前缀/包装
    q = re.sub(r"^(好的|嗯|那么|接下来)[，,、]?\s*", "", q)
    q = q.strip().strip('"').strip("“”").strip()
    # 只取第一句（防一次问三件）
    parts = re.split(r"(?<=[？?])", q)
    q = (parts[0] if parts and parts[0].strip() else q).strip()
    if not q.endswith(("？", "?")):
        q = q.rstrip("。.!！") + "？"
    # 太长、太空、明显是模板废话 → 判无效
    if len(q) > 60:
        return ""
    if len(q) < 4:
        return ""
    for bad in ("作为AI", "作为一个", "根据您刚才", "我理解您"):
        if bad in q:
            return ""
    return q


def _fallback_question(heard: str, *, anchor_hint: str = "", birth_year=None) -> str:
    """
    模型不可用时的兜底问法。**仍要接住老人的话**——只做机械改写，不装聪明。
    顺序：抓到的具体物（地名/年份）→ 锚点提示 → 通用开放问。
    """
    t = (heard or "").strip()

    # 有年份 → 直接拿年份做锚，这是最自然的接法
    y = extract_anchor_year(t)
    if y:
        if birth_year:
            age = y - int(birth_year)
            if 0 < age < 100:
                return f"{y}年那会儿，您大概{age}岁吧？那年发生了啥？"
        return f"{y}年那会儿，您还记得什么事？"

    # 抓一个「地方」的影子（很粗，够用）
    m = re.search(r"(山东|河南|河北|山西|陕西|江苏|浙江|安徽|福建|江西|湖北|湖南|"
                  r"广东|广西|四川|贵州|云南|辽宁|吉林|黑龙江|北京|上海|天津|重庆)"
                  r"([\u4e00-\u9fa5]{1,6})?(村|庄|镇|县|市)?", t)
    if m:
        place = "".join(x for x in m.groups() if x)
        return f"{place}那地方，那时候日子苦不苦？"

    if anchor_hint:
        return anchor_hint

    if t:
        # 把老人说的前半截接上来，问细节（机械、但一定接得住）
        head = t[:8].rstrip("，,。.")
        return f"您说的「{head}」，能再细讲讲不？"

    return "您想从哪段日子说起？"


def _echo_probe(heard: str) -> str:
    """老人这句没内容时的问法：换一个具体的小事，不重复问法。"""
    return "那我换个问法——您小时候，家里几口人呀？"


# ============================================================
# 七、回一句「我记下了」（让老人知道自己在被听见）
# ============================================================

def recap_line(*, n_stories: int, last_topic: str = "") -> str:
    """
    每聊几段回一句。**不是总结**（老人不需要被总结），只报「记下了多少」。
    """
    n = int(n_stories or 0)
    if n <= 0:
        return ""
    topic = (last_topic or "").strip().rstrip("。.，,")
    if topic and len(topic) <= 12:
        return f"您刚说的「{topic}」，我记下了。咱接着聊——"
    if n == 1:
        return "这段我记下了。咱接着说——"
    return f"这{n}段我都记下了。您接着说，我听着——"


# ============================================================
# 八、自测（真调模型，不算 mock）
# ============================================================

def _selftest():
    print("=== llm_brain 自测 ===")
    print("密钥：", "已配置" if llm_available() else "⚠️ 未配置（只能走降级）")

    print("\n-- 年份提取 --")
    cases = [
        ("我1958年出生的", 1958),
        ("那会儿是一九五八年", 1958),
        ("我是五八年生的", 1958),
        ("58年那阵子", 1958),
        ("九八年发大水", 1998),
        ("我今年七十了", None),
        ("家里有三亩地", None),
    ]
    bad = 0
    for txt, want in cases:
        got = extract_anchor_year(txt)
        flag = "✓" if got == want else "✗"
        if got != want:
            bad += 1
        print(f"  {flag} 「{txt}」→ {got}（期望 {want}）")

    print("\n-- 接话（真调模型）--")
    ans = "我小时候在山东农村，家里种地的，我爹也种地"
    r = next_question_from_answer(answer_text=ans, asked_question="您小时候住哪儿？")
    print(f"  老人说：{ans}")
    print(f"  下一问：{r['question']}")
    print(f"  类型：{r['kind']}  降级原因：{r['degraded_reason'] or '无'}")
    ok1 = bool(r["question"]) and "山东" in r["question"]
    print("  ✓ 接住了「山东」" if ok1 else "  ✗ 没接住老人的话")

    print("\n-- 老人没内容 --")
    r2 = next_question_from_answer(answer_text="嗯")
    print(f"  下一问：{r2['question']}（{r2['kind']}）")
    ok2 = bool(r2["question"])
    print("  ✓ 仍能问出口" if ok2 else "  ✗ 空了")

    print("\n-- 回执 --")
    print("  ", recap_line(n_stories=3, last_topic="山东老家"))

    allok = (bad == 0) and ok1 and ok2
    print("\n结论：", "✅ 全部通过" if allok else "❌ 有失败项")
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(_selftest())
