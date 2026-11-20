"""
narrative_polish.py —— 把老人的语音转写碎片，整理成「能读、能印」的自述正文
====================================================================
什么时候用：家书卡出图前、成书正文生成时、故事详情页「整篇通读」时。
解决的问题：ASR 转写是**实录**——"所以的话。，我就现在做了几件事情啊，我记得。
          我很佩服我的，我很喜欢我的嫂子。应该这样说，他虽然不声不响，但是嗯，
          该出嗯。该出想法的时候会有他的想法。"
          老人念着尴尬，印出来更尴尬。家书卡要的是**他的自述**，不是录音听写。

三条铁律（sandy 2026-11-20 定，写死在这里，改之前先想清楚）：
  1. **只整理，不编造。** 不许加原文没有的人名、地名、年份、事件、评价。
     原文没说的，一个字都不许补。宁可这段短，也不许圆成故事。
  2. **保留老人的说话口气。** 第一人称，口语感留着（"我妈说""那会儿"），
     不许改成书面语腔调的"回忆录体"，更不许加感叹和抒情。
  3. **整理不出就退回原文。** 模型不可用 / 输出跑偏 / 掺进原文没有的人物地名
     → 直接返回原文切好的句子，**绝不空手、绝不硬编**。

输出结构：段落 list（每段 1~3 句），家书卡按段排版，成书按段落章。
"""

from __future__ import annotations

import re
from typing import List, Optional

MAX_INPUT_CHARS = 1400      # 一次整理的上限；超了截断（一屏家书卡也印不下更多）
MIN_GOOD_CHARS = 12         # 整理结果短于这个 → 判定为模型没干活，退回原文


def _split_sentences(raw: str) -> List[str]:
    """把实录切成句子（按换行 + 句读）。保留原句，不做任何改写。"""
    text = (raw or "").replace("\r", "")
    out: List[str] = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        for p in re.split(r"(?<=[。！？])", line):
            p = p.strip()
            if p:
                out.append(p)
    return out


_NOISE_PREFIX = ("嗯", "啊", "哦", "呃", "那个", "然后呢")


def _drop_fillers(sentence: str) -> str:
    """只删**句首**的语气词和中间的"嗯/啊"卡顿，不删实词。"""
    s = sentence.strip()
    changed = True
    while changed:
        changed = False
        for p in _NOISE_PREFIX:
            if s.startswith(p) and len(s) > len(p) + 2:
                s = s[len(p):].lstrip("，、 ")
                changed = True
    # 中间的卡顿：嗯/啊 后面直接跟句读 → 删掉
    s = re.sub(r"[嗯啊呃]+(?=[，。！？])", "", s)
    s = re.sub(r"，{2,}", "，", s)
    s = s.strip("，、 ")
    return s


def polish(raw: str, *, max_chars: int = 320) -> List[str]:
    """把实录整理成自述段落。返回 [段1, 段2, ...]；失败退回原文句子。

    返回值永远非空（除非 raw 本身就是空的 → 返回 []）。
    """
    text = (raw or "").strip()
    if not text:
        return []
    text = text[:MAX_INPUT_CHARS]

    # 先做不依赖模型的清洗：删句首语气词、去重复卡顿
    sentences = [_drop_fillers(s) for s in _split_sentences(text)]
    sentences = [s for s in sentences if s and len(re.sub(r"[\s，。！？]", "", s)) > 1]
    if not sentences:
        return []
    cleaned = "".join(sentences)

    paras = _polish_with_llm(cleaned, max_chars=max_chars)
    if paras:
        return paras

    # ---- 降级：不整理，但至少把句子按语义断成 2~3 段，别糊成一整坨 ----
    return _group_sentences(sentences, max_chars=max_chars)


def _group_sentences(sentences: List[str], *, max_chars: int = 320) -> List[str]:
    """模型不可用时的降级：按长度把句子攒成段，不改字。"""
    paras: List[str] = []
    cur = ""
    for s in sentences:
        if cur and len(cur) + len(s) > max_chars // 2:
            paras.append(cur)
            cur = s
        else:
            cur += s
        if len("".join(paras)) + len(cur) >= max_chars:
            break
    if cur:
        paras.append(cur)
    return paras[:3]


def _polish_with_llm(cleaned: str, *, max_chars: int = 320) -> List[str]:
    """让模型整理。任何不对劲（跑偏/掺假/太短）→ 返回 [] 让上层降级。"""
    try:
        import llm_brain
        if not llm_brain.llm_available():
            return []
    except Exception:
        return []

    system = (
        "你在帮一位老人整理他自己的口述，整理成他自己讲的一段话。\n"
        "规矩（违反任何一条都算失败）：\n"
        "1. **只整理，不编造**：不许加原文里没有的人名、地名、年份、事件、评价。"
        "原文没说的一个字都不补。\n"
        "2. **保留他说话的口气**：第一人称，口语留着，不要改成书面语，"
        "不要加抒情、不要加感叹、不要加形容词渲染。\n"
        "3. 只做三件事：删掉语气词和重复卡顿；把没说完的半句并进相邻句；按意思分段。\n"
        "4. 分成 1~3 段，每段 1~3 句。总长不超过 " + str(max_chars) + " 字。\n"
        "5. 只输出整理后的正文，不要标题、不要解释、不要引号。"
    )
    msgs = [{"role": "system", "content": system},
            {"role": "user", "content": cleaned}]
    try:
        out, why = llm_brain._chat(msgs, temperature=0.35, max_tokens=700)
    except Exception:
        return []
    body = (out or "").strip()
    if not body or len(body) < MIN_GOOD_CHARS:
        return []
    # 防跑偏：模型把规矩复述出来了 / 带了 markdown / 带了"以下是"
    for bad in ("规矩", "以下是", "整理后", "```", "作为AI", "——"):
        if bad in body:
            return []

    paras = [p.strip() for p in re.split(r"\n{1,}", body) if p.strip()]
    paras = [p for p in paras if len(p) > 1]
    if not paras:
        return []

    # ---- 防编造闸门：模型输出里出现原文没有的年份/引号内容 → 判失败 ----
    src_years = set(re.findall(r"\d{4}", cleaned))
    out_years = set(re.findall(r"\d{4}", body))
    if out_years - src_years:
        return []          # 凭空冒出来的年份 = 编造，直接退回原文

    # 长度失控（模型把话展开了）→ 也退
    if len(body) > len(cleaned) * 1.6 + 40:
        return []

    return paras


def join_for_card(paras: List[str], *, max_chars: int = 330) -> str:
    """家书卡用：把段落用换行接起来，控总长。"""
    out, used = [], 0
    for p in paras:
        if used + len(p) > max_chars and out:
            break
        out.append(p)
        used += len(p)
    return "\n".join(out)
