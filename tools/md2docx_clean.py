#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MD -> DOCX 彻底清洗版
在转换前先把所有 AI 痕迹字符清洗掉：
  ** 星号 -> 直接去掉（保留文字）
  ` 反引号 -> 去掉
  emoji(⚠️✅❌★☆📌🎯等) -> 去掉
  圈码 1️⃣-🔟 -> 换成 1. 2. 等纯数字
  --- 分隔线 -> 细灰线
  表格 -> Word 真表格
转换后二次校验 document.xml，确认没有残留。
"""
import re, os, sys, zipfile
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn, nsdecls
from docx.oxml import parse_xml

CIRCLED = {'1️⃣':'1.','2️⃣':'2.','3️⃣':'3.','4️⃣':'4.','5️⃣':'5.','6️⃣':'6.','7️⃣':'7.','8️⃣':'8.','9️⃣':'9.','🔟':'10.','0️⃣':'0.'}
EMOJI_RE = re.compile('[\u2600-\u27BF\uFE0F\u2B00-\u2BFF\U0001F300-\U0001FAFF\u2190-\u21FF\u2705\u274C\u26A0]')

def clean(text):
    for k, v in CIRCLED.items():
        text = text.replace(k, v)
    text = EMOJI_RE.sub('', text)
    text = text.replace('`', '')
    text = text.replace('**', '')       # 星号直接去掉，文字保留
    text = re.sub(r'(?<!\*)\*(?!\*)', '', text)  # 单个星号也去掉
    text = text.replace('\u200b', '')
    return text

def add_runs(p, text):
    """把 **加粗** 转成 Word 真加粗；其余按普通文本"""
    for part in re.split(r'(\*\*.*?\*\*)', text):
        if not part:
            continue
        if part.startswith('**') and part.endswith('**') and len(part) > 4:
            r = p.add_run(part[2:-2]); r.bold = True
        else:
            p.add_run(part)

def heading(doc, level, text):
    text = clean(text)
    if level == 1:
        h = doc.add_heading(text, level=1)
        for r in h.runs: r.font.color.rgb = RGBColor(0x1A,0x47,0x8A); r.font.size = Pt(20)
    elif level == 2:
        h = doc.add_heading(text, level=2)
        for r in h.runs: r.font.color.rgb = RGBColor(0x1A,0x47,0x8A); r.font.size = Pt(15)
    elif level == 3:
        h = doc.add_heading(text, level=3)
        for r in h.runs: r.font.color.rgb = RGBColor(0x2D,0x5F,0x9E); r.font.size = Pt(13)
    else:
        h = doc.add_heading(text, level=4)
        for r in h.runs: r.font.color.rgb = RGBColor(0x33,0x33,0x33); r.font.size = Pt(12)
    for r in h.runs:
        r.font.name = '微软雅黑'
        r._element.rPr.rFonts.set(qn('w:eastAsia'), '微软雅黑')

def para(doc, text, indent=0):
    text = clean(text)
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(6)
    p.paragraph_format.line_spacing = 1.4
    if indent: p.paragraph_format.left_indent = Cm(indent)
    add_runs(p, text)
    for r in p.runs:
        r.font.name = '微软雅黑'
        r._element.rPr.rFonts.set(qn('w:eastAsia'), '微软雅黑')
    return p

def bullet(doc, text):
    text = clean(text)
    p = doc.add_paragraph(style='List Bullet')
    p.paragraph_format.space_after = Pt(3)
    add_runs(p, text)
    for r in p.runs:
        r.font.name = '微软雅黑'
        r._element.rPr.rFonts.set(qn('w:eastAsia'), '微软雅黑')
    return p

def quote(doc, text):
    text = clean(text)
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.8)
    p.paragraph_format.space_before = Pt(4)
    p.paragraph_format.space_after = Pt(4)
    p.paragraph_format.line_spacing = 1.4
    add_runs(p, text)
    for r in p.runs:
        r.font.name = '微软雅黑'
        r._element.rPr.rFonts.set(qn('w:eastAsia'), '微软雅黑')
    pPr = p.paragraph_format.element.get_or_add_pPr()
    pPr.append(parse_xml(f'<w:pBdr {nsdecls("w")}><w:left w:val="single" w:sz="12" w:space="8" w:color="1A478A"/></w:pBdr>'))
    return p

def add_table(doc, lines, start):
    headers = [clean(h.strip()) for h in lines[start].split('|')[1:-1]]
    rows, i = [], start + 2
    while i < len(lines):
        ln = lines[i].strip()
        if not ln or not ln.startswith('|'): break
        rows.append([clean(c.strip()) for c in ln.split('|')[1:-1]])
        i += 1
    t = doc.add_table(rows=1+len(rows), cols=len(headers))
    t.style = 'Table Grid'
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for j, h in enumerate(headers):
        cell = t.rows[0].cells[j]; cell.text = ''
        p = cell.paragraphs[0]; r = p.add_run(h)
        r.bold = True; r.font.size = Pt(10); r.font.color.rgb = RGBColor(0xFF,0xFF,0xFF)
        r.font.name = '微软雅黑'; r._element.rPr.rFonts.set(qn('w:eastAsia'), '微软雅黑')
        cell._tc.get_or_add_tcPr().append(parse_xml(f'<w:shd {nsdecls("w")} w:fill="1A478A" w:val="clear"/>'))
    for ri, row in enumerate(rows):
        for ci, ct in enumerate(row):
            if ci >= len(headers): break
            cell = t.rows[ri+1].cells[ci]; cell.text = ''
            p = cell.paragraphs[0]
            add_runs(p, ct)
            for r in p.runs:
                r.font.size = Pt(10); r.font.name = '微软雅黑'
                r._element.rPr.rFonts.set(qn('w:eastAsia'), '微软雅黑')
            if ri % 2 == 1:
                cell._tc.get_or_add_tcPr().append(parse_xml(f'<w:shd {nsdecls("w")} w:fill="F5F7FA" w:val="clear"/>'))
    doc.add_paragraph()
    return i

def convert(md_path, docx_path):
    with open(md_path, encoding='utf-8') as f:
        lines = f.read().split('\n')
    doc = Document()
    st = doc.styles['Normal']
    st.font.name = '微软雅黑'; st.font.size = Pt(11)
    st.element.rPr.rFonts.set(qn('w:eastAsia'), '微软雅黑')
    for lv in range(1, 5):
        hs = doc.styles[f'Heading {lv}']
        hs.element.rPr.rFonts.set(qn('w:eastAsia'), '微软雅黑')

    i, in_code, buf = 0, False, []
    while i < len(lines):
        ln = lines[i]
        if ln.strip().startswith('```'):
            if in_code:
                p = doc.add_paragraph(); r = p.add_run('\n'.join(buf)); r.font.name='Consolas'; r.font.size=Pt(9)
                buf=[]; in_code=False; i+=1; continue
            in_code=True; i+=1; continue
        if in_code: buf.append(ln); i+=1; continue
        if not ln.strip(): i+=1; continue
        hm = re.match(r'^(#{1,4})\s+(.+)$', ln)
        if hm:
            heading(doc, len(hm.group(1)), hm.group(2).strip()); i+=1; continue
        if re.match(r'^-{3,}$', ln.strip()) or re.match(r'^─{3,}$', ln.strip()):
            p = doc.add_paragraph(); p.paragraph_format.space_before=Pt(8); p.paragraph_format.space_after=Pt(8)
            r = p.add_run('─'*58); r.font.color.rgb = RGBColor(0xBB,0xBB,0xBB); r.font.size = Pt(8)
            i+=1; continue
        if ln.strip().startswith('|') and i+1 < len(lines) and re.match(r'^\|[\s:|-]+\|$', lines[i+1].strip()):
            i = add_table(doc, lines, i); continue
        if ln.strip().startswith('|'):
            # 表格行但没有分隔符 -> 当作普通段落
            para(doc, ln.strip().strip('|').replace('|', '  ')); i+=1; continue
        if ln.strip().startswith('>'):
            quote(doc, re.sub(r'^>\s*', '', ln)); i+=1; continue
        if re.match(r'^[\s]*[-*]\s+', ln):
            bullet(doc, re.sub(r'^[\s]*[-*]\s+', '', ln)); i+=1; continue
        if re.match(r'^[\s]*\d+[\.\)]\s+', ln):
            para(doc, re.sub(r'^[\s]*\d+[\.\)]\s+', '', ln), indent=0.6); i+=1; continue
        para(doc, ln.strip()); i+=1
    doc.save(docx_path)

    # ===== 交付前自动校验 =====
    z = zipfile.ZipFile(docx_path)
    txt = re.sub(r'<[^>]+>', '', z.read('word/document.xml').decode('utf-8','ignore'))
    bad = {}
    for pat, n in [(r'\*\*','星号'), (r'`','反引号'), (r'[\u2600-\u27BF\uFE0F\U0001F300-\U0001FAFF]','emoji'),
                   (r'^#{1,6}\s','井号'), (r'[1-9]️⃣|🔟','圈码')]:
        c = len(re.findall(pat, txt, re.M))
        if c: bad[n] = c
    print("✅ 已生成:", docx_path)
    print("   校验结果:", "❌ 仍有残留 -> " + str(bad) if bad else "✅ 无 AI 痕迹字符残留")
    return not bad

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("用法: python md2docx_clean.py input.md output.docx"); sys.exit(1)
    if os.path.abspath(sys.argv[1]) == os.path.abspath(sys.argv[2]):
        print("❌ 输入输出同名，会覆盖源文件"); sys.exit(1)
    ok = convert(sys.argv[1], sys.argv[2])
    sys.exit(0 if ok else 2)
