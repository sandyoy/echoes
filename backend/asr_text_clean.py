# -*- coding: utf-8 -*-
"""
asr_text_clean.py —— 语音转写文字清洗

★ 11-10 sandy 真机实测报的三个病（全部在这一层治）：

  ① 「2020年」被识别成「二零。020年」—— 中文数字+标点混着年份，读出来是断的
  ② 「啊，我在，嗯。」这种口语垃圾被当成正文显示，老人看了觉得丢人
  ③ 同一件事语音 + 转写各存一条 → 时间轴条数对不上

铁律：
  · 只清洗 **显示/入库的文本**，不动原声文件（keep_original_voice 恒 true）
  · 清洗不能吃掉意思：宁少删不多删，删掉的只能是纯语气词
  · 任何函数都不抛异常（清洗失败就原样返回，不能因为清洗把记录搞丢）
"""

import re

# 只在**整句/整段几乎全是这些词**时才判为垃圾；出现在正文中间一律保留
FILLERS = (
    "嗯", "啊", "呃", "哦", "唉", "诶", "呀", "哈", "唉呀", "哦哦",
    "那个", "这个", "就是", "然后", "呢", "吧", "嘛", "我说", "是吧",
    "对对对", "好好好", "呃呃",
)

_CN_DIGIT = {"零": 0, "〇": 0, "一": 1, "二": 2, "三": 3, "四": 4,
             "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_UNIT = {"十": 10, "百": 100, "千": 1000}


def _cn_to_int(s: str) -> int:
    """把「二零二零」「一千九百六十八」这类中文数字转成 int；失败返回 -1。"""
    s = (s or "").strip()
    if not s:
        return -1
    # 纯逐位读法：二零二零
    if all(ch in _CN_DIGIT for ch in s):
        if len(s) == 4:
            return _CN_DIGIT[s[0]] * 1000 + _CN_DIGIT[s[1]] * 100 + \
                   _CN_DIGIT[s[2]] * 10 + _CN_DIGIT[s[3]]
        return int("".join(str(_CN_DIGIT[c]) for c in s))
    # 带单位读法：一九六八 / 一千九百六十八
    total, section, num = 0, 0, 0
    for ch in s:
        if ch in _CN_DIGIT:
            num = _CN_DIGIT[ch]
        elif ch in _CN_UNIT:
            u = _CN_UNIT[ch]
            section += (num if num else 1) * u
            num = 0
        else:
            return -1
    total = section + num
    return total if 1000 <= total <= 2100 else -1


_YEAR_PATTERNS = [
    # 「二零。020年」「二零二零年」「二千零二十年」
    (re.compile(r"([零〇一二三四五六七八九]{4})\s*[。．\.、,，]?\s*(\d{3})\s*年?"), "cn_split"),
    (re.compile(r"([零〇一二三四五六七八九]{4})\s*年"), "cn4"),
    (re.compile(r"([一二三四五六七八九千]{2,6})\s*年"), "cn_any"),
    (re.compile(r"(\d{4})\s*年"), "num"),
]


def fix_years(text: str) -> str:
    """
    治「2020年 → 二零。020年」。
    策略：把所有"看起来是年份"的写法统一成阿拉伯数字+年，其余原样不动。
    绝不改动非年份的数字（如"十八块""三十岁"）。
    """
    if not text:
        return text
    out = text

    # ① 「二零。020年」这类：年份被切成"中文两截 + 标点 + 阿拉伯残尾"
    #    例：二零。020 → 2020 / 二零。20 → 2020 / 一九。六八 → 1968
    def _join_split(m):
        head, sep, tail = m.group(1), m.group(2), m.group(3)
        y = _cn_to_int(head) * 100 + int(tail)
        return f"{y}年" if 1900 <= y <= 2099 else m.group(0)

    # 中文2位 + 标点 + 阿拉伯2位
    out = re.sub(r"([零〇一二三四五六七八九]{2})\s*[。．\.、,，:：]\s*(\d{2})\s*(?!\d)年?", _join_split, out)
    # 中文2位 + 标点 + 阿拉伯3位（如 二零。020）
    out = re.sub(r"([零〇一二三四五六七八九]{2})\s*[。．\.、,，:：]\s*(\d{3})\s*年?",
                 lambda m: f"{_cn_to_int(m.group(1)) * 100 + int(m.group(2)[1:])}年"
                 if 1900 <= _cn_to_int(m.group(1)) * 100 + int(m.group(2)[1:]) <= 2099 else m.group(0), out)
    # 中文2位 + 标点 + 中文2位（如 一九。六八）
    out = re.sub(r"([零〇一二三四五六七八九]{2})\s*[。．\.、,，:：]\s*([零〇一二三四五六七八九]{2})\s*年?",
                 lambda m: f"{_cn_to_int(m.group(1)) * 100 + _cn_to_int(m.group(2))}年"
                 if 1900 <= _cn_to_int(m.group(1)) * 100 + _cn_to_int(m.group(2)) <= 2099 else m.group(0), out)

    # ② 四位中文年份：「二零二零年」→ 2020年
    def _fix_cn4(m):
        y = _cn_to_int(m.group(1))
        return f"{y}年" if 1900 <= y <= 2099 else m.group(0)

    out = re.sub(r"([零〇一二三四五六七八九]{4})\s*年", _fix_cn4, out)

    # ③ 带单位中文年份：「一九六八年」
    def _fix_cn_any(m):
        y = _cn_to_int(m.group(1))
        return f"{y}年" if 1900 <= y <= 2099 else m.group(0)

    out = re.sub(r"([一二三四五六七八九][零〇一二三四五六七八九十百千]{1,6})\s*年", _fix_cn_any, out)

    # ④ 已被拆成两截的：「2020 年」→「2020年」
    out = re.sub(r"(\d{4})\s+年", r"\1年", out)
    return out


def strip_fillers(text: str) -> str:
    """
    治「啊，我在，嗯。」被当正文。
    只在**分句里全是语气词**时整句删掉；有实义内容的分句一律保留。
    """
    if not text:
        return text
    # 按中文标点切句
    parts = re.split(r"([，。！？、；,.!?;…\s]+)", text)
    kept = []
    for seg in parts:
        if not seg:
            continue
        if re.fullmatch(r"[，。！？、；,.!?;…\s]+", seg):
            kept.append(seg)
            continue
        core = seg.strip()
        # 去掉标点后，逐字剥离语气词，看还剩不剩实义字
        residue = core
        for f in sorted(FILLERS, key=len, reverse=True):
            residue = residue.replace(f, "")
        if len(residue.strip()) == 0:
            continue          # 整句都是"嗯啊那个" → 丢掉
        # 句子里只剩 1 个实义字（如「我」「在」）且原句 ≤4 字 → 也是语气残渣
        if len(residue.strip()) <= 1 and len(core) <= 4:
            continue
        # 剥完语气词后只剩「我我」「你你」这类重复单字 → 也是残渣
        if len(residue.strip()) <= 2 and len(set(residue.strip())) == 1:
            continue
        kept.append(seg)
    out = "".join(kept)
    # 「我在。2020年」这类：语气句被删后留下的句号，若后面不是句首 → 降级为逗号
    # 这里先统一把孤立的「X。Y」里 X 过短的情况处理掉
    out = re.sub(r"^[，。！？、；,.!?;…\s]+", "", out)     # 开头标点
    out = re.sub(r"[，、]+[。！？]", lambda m: m.group(0)[-1], out)  # 「，。」→「。」
    out = re.sub(r"([，。！？、；])\1+", r"\1", out)        # 重复标点
    out = re.sub(r"[，、]+$", "", out)                    # 结尾悬空逗号
    out = re.sub(r"^[。！？、；,.!?;…]+", "", out)         # 二次清开头（防「。我在」）
    return out.strip()


def dedup_chars(text: str) -> str:
    """
    治老人结巴重复：「我我我那时候」→「我那时候」；「对对对」已算语气词。
    只处理**同字连续重复**，且只在 2~4 次连读时压缩；不碰「年年」「家家」这类正常叠词。
    """
    if not text:
        return text
    # 显式白名单式的正常叠词（避免误伤）
    KEEP_DOUBLE = {"年年", "家家", "天天", "人人", "点点", "渐渐", "刚刚", "常常"}

    # 同一个字连续出现 2~4 次 → 压成 1 个；但落在白名单叠词里的 2 连读保留
    def _shrink(m):
        run = m.group(0)
        ch = m.group(1)
        if len(run) == 2 and run in KEEP_DOUBLE:
            return run          # 「年年」「家家」保留
        return ch

    out = re.sub(r"([\u4e00-\u9fa5])\1{1,3}", _shrink, text)
    return out


def clean(text: str) -> str:
    """对外唯一入口：先修年份，再删纯语气句，压结巴重复，最后收标点。永不抛异常。"""
    try:
        t = (text or "").strip()
        if not t:
            return ""
        t = fix_years(t)
        t = strip_fillers(t)
        t = dedup_chars(t)
        # 压完结巴后可能只剩「我。」「你。」这类单字残句 → 整段判空
        _core = re.sub(r"[，。！？、；,.!?;…\s]", "", t)
        if len(_core) <= 1 or (len(_core) <= 2 and len(set(_core)) == 1):
            return ""
        t = re.sub(r"[ \t]+", " ", t)
        t = re.sub(r"([，。！？、；])\1+", r"\1", t)
        t = re.sub(r"[，、]+[。！？]", lambda m: m.group(0)[-1], t)
        t = re.sub(r"^[，。！？、；,.!?;…\s]+", "", t)
        t = re.sub(r"[，、]+$", "", t)
        return t.strip()
    except Exception:
        return text or ""


def dedup_same(prev_text: str, new_text: str) -> bool:
    """
    治「同一件事语音 + 转写存成两条，条数对不上」。
    判定为同一条的标准：清洗后**首尾各去掉标点**完全相等，或一方是另一方的开头/包含。
    """
    try:
        a = re.sub(r"[\s，。！？、；,.!?;…]", "", str(prev_text or ""))
        b = re.sub(r"[\s，。！？、；,.!?;…]", "", str(new_text or ""))
        if not a or not b:
            return False
        if a == b:
            return True
        short, long_ = (a, b) if len(a) <= len(b) else (b, a)
        # 短的占长的 85% 以上且是包含关系 → 视为重复（老人同一段话转了两遍）
        return short in long_ and len(short) >= max(6, int(len(long_) * 0.85))
    except Exception:
        return False
