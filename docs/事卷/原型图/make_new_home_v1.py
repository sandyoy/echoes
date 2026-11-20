#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""往事可追忆 · 新结构原型（2026-11-20 sandy 定节奏）
   结构 = 首页一件大事：一个大按钮「我要说」+ 旁边「找人说」
          说完之后 = 一个弹层，三件事（看→发/存/整理）
   出 4 屏：①首页 ②按住中(录音态) ③说完之后(弹层) ④三个入口(原三块)下沉到哪
   全部 375x812 @S=2
"""
import os
from PIL import Image, ImageDraw, ImageFont

OUT = "/home/ubuntu/echoes/docs/事卷/原型图"
os.makedirs(OUT, exist_ok=True)
S = 2
DW, DH = 375, 812
W, H = DW * S, DH * S

BG = "#FBF8F2"
CARD = "#FFFFFF"
PRIMARY = "#E0904F"
PRIMARY_D = "#D07C3C"
INK = "#3A322C"
INK2 = "#8C8078"
LINE = "#ECE5DA"
TEAL = "#63A9A2"
GOLD = "#C79A5A"
GREEN = "#7FAE86"
CHIP = "#F7EEE1"

FP = "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"
def F(s): return ImageFont.truetype(FP, int(s * S))
def px(v): return int(v * S)

issues = []
def chk(name, x1, y1, x2, y2):
    if x1 < 0 or x2 > DW or y1 < 0 or y2 > DH:
        issues.append(f"{name} 越界 ({x1},{y1})-({x2},{y2})")

def rrect(d, b, r, fill=None, outline=None, width=1):
    d.rounded_rectangle([px(b[0]), px(b[1]), px(b[2]), px(b[3])], radius=px(r),
                        fill=fill, outline=outline, width=px(width) if width else 0)
def circle(d, cx, cy, r, fill=None, outline=None, width=1):
    d.ellipse([px(cx-r), px(cy-r), px(cx+r), px(cy+r)], fill=fill, outline=outline,
              width=px(width) if width else 0)
def text(d, xy, s, f, fill, anchor="la"):
    d.text((px(xy[0]), px(xy[1])), s, font=f, fill=fill, anchor=anchor)
def tw(d, s, f):
    b = d.textbbox((0, 0), s, font=f); return (b[2]-b[0]) / S

def icon(d, cx, cy, R, kind, color="#FFFFFF", lw=3.4):
    w = px(lw)
    def L(x1, y1, x2, y2): d.line([px(x1), px(y1), px(x2), px(y2)], fill=color, width=w)
    def A(box, a1, a2): d.arc([px(box[0]), px(box[1]), px(box[2]), px(box[3])], a1, a2, fill=color, width=w)
    if kind == "mic":
        bw, bh = R*0.66, R*1.05
        rrect(d, [cx-bw/2, cy-R*0.72, cx+bw/2, cy-R*0.72+bh], bw/2, outline=color, width=lw)
        A((cx-R*0.52, cy-R*0.52, cx+R*0.52, cy+R*0.52), 0, 180)
        L(cx, cy+R*0.52, cx, cy+R*0.86); L(cx-R*0.36, cy+R*0.86, cx+R*0.36, cy+R*0.86)
    elif kind == "chat":
        rrect(d, [cx-R*0.82, cy-R*0.62, cx+R*0.82, cy+R*0.42], R*0.24, outline=color, width=lw)
        d.polygon([(px(cx-R*0.30), px(cy+R*0.42)), (px(cx+R*0.02), px(cy+R*0.42)),
                   (px(cx-R*0.30), px(cy+R*0.82))], fill=color)
        for dx in (-0.34, 0, 0.34): circle(d, cx+R*dx, cy-R*0.10, R*0.09, fill=color)
    elif kind == "text":
        for dy in (-0.36, 0, 0.36): L(cx-R*0.60, cy+R*0.60*dy, cx+R*0.60, cy+R*0.60*dy)
    elif kind == "book":
        L(cx-R*0.10, cy-R*0.70, cx-R*0.10, cy+R*0.70); A((cx-R*0.78, cy-R*0.70, cx-R*0.10, cy+R*0.30), 90, 270)
        L(cx-R*0.78, cy-R*0.70, cx-R*0.10, cy-R*0.70); L(cx-R*0.78, cy+R*0.30, cx-R*0.10, cy+R*0.30)
        A((cx+R*0.10, cy-R*0.70, cx+R*0.78, cy+R*0.30), 270, 90)
        L(cx+R*0.78, cy-R*0.70, cx+R*0.10, cy-R*0.70); L(cx+R*0.78, cy+R*0.30, cx+R*0.10, cy+R*0.30)
    elif kind == "clock":
        circle(d, cx, cy, R*0.72, outline=color, width=lw); L(cx, cy-R*0.40, cx, cy); L(cx, cy, cx+R*0.30, cy+R*0.18)
    elif kind == "user":
        circle(d, cx, cy-R*0.26, R*0.30, outline=color, width=lw); A((cx-R*0.52, cy+R*0.02, cx+R*0.52, cy+R*1.06), 180, 360)
    elif kind == "users":
        circle(d, cx-R*0.22, cy-R*0.30, R*0.24, outline=color, width=lw)
        A((cx-R*0.58, cy-R*0.02, cx+R*0.14, cy+R*0.62), 180, 360)
        A((cx-R*0.02, cy-R*0.02, cx+R*0.70, cy+R*0.62), 180, 360)
    elif kind == "plus":
        L(cx-R*0.50, cy, cx+R*0.50, cy); L(cx, cy-R*0.50, cx, cy+R*0.50)
    elif kind == "chev":
        L(cx-R*0.16, cy-R*0.34, cx+R*0.20, cy); L(cx+R*0.20, cy, cx-R*0.16, cy+R*0.34)
    elif kind == "play":
        d.polygon([(px(cx-R*0.28), px(cy-R*0.46)), (px(cx+R*0.46), px(cy)), (px(cx-R*0.28), px(cy+R*0.46))], fill=color)
    elif kind == "dots":
        for dx in (-0.5, 0, 0.5): circle(d, cx+R*dx, cy, R*0.14, fill=color)
    elif kind == "pen":
        d.line([px(cx-R*0.5), px(cy+R*0.5), px(cx+R*0.38), px(cy-R*0.38)], fill=color, width=w)
        d.polygon([(px(cx-R*0.66), px(cy+R*0.66)), (px(cx-R*0.30), px(cy+R*0.54)),
                   (px(cx-R*0.50), px(cy+R*0.34))], fill=color)
    elif kind == "photo":
        rrect(d, [cx-R*0.8, cy-R*0.62, cx+R*0.8, cy+R*0.62], R*0.16, outline=color, width=lw)
        circle(d, cx-R*0.34, cy-R*0.24, R*0.16, outline=color, width=lw)
        d.polygon([(px(cx-R*0.7), px(cy+R*0.5)), (px(cx-R*0.05), px(cy-R*0.1)), (px(cx+R*0.7), px(cy+R*0.5))], fill=color)
    elif kind == "video":
        rrect(d, [cx-R*0.8, cy-R*0.55, cx+R*0.3, cy+R*0.55], R*0.16, outline=color, width=lw)
        d.polygon([(px(cx+R*0.34), px(cy-R*0.30)), (px(cx+R*0.84), px(cy-R*0.5)),
                   (px(cx+R*0.84), px(cy+R*0.5)), (px(cx+R*0.34), px(cy+R*0.30))], fill=color)
    elif kind == "eye":
        A((cx-R*0.8, cy-R*0.5, cx+R*0.8, cy+R*0.5), 0, 360); circle(d, cx, cy, R*0.24, fill=color)
    elif kind == "lock":
        rrect(d, [cx-R*0.5, cy-R*0.05, cx+R*0.5, cy+R*0.62], R*0.14, outline=color, width=lw)
        A((cx-R*0.32, cy-R*0.62, cx+R*0.32, cy+R*0.10), 180, 360)
    elif kind == "home":
        d.polygon([(px(cx), px(cy-R*0.72)), (px(cx-R*0.78), px(cy-R*0.02)), (px(cx+R*0.78), px(cy-R*0.02))], fill=color)
        rrect(d, [cx-R*0.56, cy-R*0.10, cx+R*0.56, cy+R*0.68], R*0.10, outline=color, width=lw)
    elif kind == "send":
        d.polygon([(px(cx-R*0.72), px(cy-R*0.60)), (px(cx+R*0.74), px(cy)), (px(cx-R*0.72), px(cy+R*0.60)),
                   (px(cx-R*0.40), px(cy))], fill=color)
    elif kind == "save":
        rrect(d, [cx-R*0.55, cy-R*0.70, cx+R*0.55, cy+R*0.70], R*0.14, outline=color, width=lw)
        L(cx-R*0.55, cy+R*0.30, cx+R*0.55, cy+R*0.30)
        L(cx-R*0.24, cy-R*0.30, cx, cy-R*0.02); L(cx, cy-R*0.02, cx+R*0.24, cy-R*0.30)
    elif kind == "sparkle":
        L(cx, cy-R*0.72, cx, cy+R*0.72); L(cx-R*0.72, cy, cx+R*0.72, cy)
        L(cx-R*0.44, cy-R*0.44, cx+R*0.44, cy+R*0.44); L(cx+R*0.44, cy-R*0.44, cx-R*0.44, cy+R*0.44)

def statusbar(d):
    text(d, (24, 22), "9:41", F(15), "#000")
    for i, h in enumerate([8, 12, 16, 20]):
        d.rectangle([px(300+i*9), px(30-h), px(300+i*9+6), px(30)], fill=INK if i < 3 else "#00000030")
    rrect(d, [DW-30, 20, DW-9, 32], 3, outline=INK, width=1.4)
    d.rectangle([px(DW-28), px(22), px(DW-13), px(30)], fill=INK)

def newpage():
    img = Image.new("RGB", (W, H), BG); return img, ImageDraw.Draw(img)

def save(img, name):
    p = os.path.join(OUT, name + ".png"); img.save(p); print("OK", p); return p

def topbar(d, subtitle=None, big=False):
    ty = 74
    text(d, (22, ty), "往事可追忆", F(21 if not big else 25), INK)
    if subtitle:
        text(d, (22, ty+28), subtitle, F(12), INK2)
    circle(d, DW-42, ty+12, 17, fill="#F1E4D6")
    icon(d, DW-42, ty+12, 9, "user", color=PRIMARY, lw=2.4)

def tabbar(d, active=0):
    ty = 742
    d.rectangle([0, px(ty), W, H], fill="#FFFFFF")
    d.line([0, px(ty), W, px(ty)], fill=LINE, width=px(1))
    tabs = [("home", "首页"), ("pen", "我的故事"), ("clock", "时间轴"), ("user", "家里人")]
    cw = DW / 4
    for i, (ic, lb) in enumerate(tabs):
        cx = cw*i + cw/2
        col = PRIMARY if i == active else "#B3A79B"
        icon(d, cx, ty+26, 11, ic, color=col, lw=2.8 if i == active else 2.4)
        text(d, (cx, ty+48), lb, F(10.5), col, "mm")

# ============================================================
# 屏 1 · 首页：就一个大按钮
# ============================================================
img, d = newpage()
d.rectangle([0, 0, W, px(56)], fill=BG); statusbar(d)
topbar(d, "想说啥就说啥")

# 主标题（给老人一句最直白的话）
text(d, (DW/2, 150), "今天想说说谁、说说哪件事？", F(19), INK, "mm")
text(d, (DW/2, 180), "按住下面这个大圆，说完松手就行", F(12.5), INK2, "mm")

# 大圆按钮
CX, CY, RB = DW/2, 330, 104
# 外圈柔光
for i, a in enumerate([0.10, 0.16, 0.24]):
    circle(d, CX, CY, RB + 26 - i*8, fill=None, outline="#E0904F", width=2)
circle(d, CX, CY, RB, fill=PRIMARY)
circle(d, CX, CY, RB-10, fill=None, outline="#FFFFFF55", width=2)
icon(d, CX, CY-24, 40, "mic", color="#FFFFFF", lw=5.0)
text(d, (CX, CY+46), "我要说", F(26), "#FFFFFF", "mm")
text(d, (CX, CY+RB+34), "按住说话 · 松手就停", F(14), PRIMARY_D, "mm")

# 旁边第二个按钮：找人说（比主按钮小一档，但不降级成小字条）
find_y = 570
rrect(d, [40, find_y, DW-40, find_y+72], 36, fill="#FFFFFF", outline="#E9D9C6", width=1.5)
icon(d, 82, find_y+36, 17, "users", color=TEAL, lw=2.8)
text(d, (112, find_y+22), "找人说", F(17), INK)
text(d, (112, find_y+45), "想聊的人不在旁边？我陪您聊", F(11.5), INK2)
icon(d, DW-72, find_y+36, 9, "chev", color="#C9BDB0", lw=2.6)

# 提示：说过的都在「我的故事」里
text(d, (DW/2, 668), "说过的都存着，在下面「我的故事」里能翻到", F(11.5), INK2, "mm")

tabbar(d, 0)
chk("btn", CX-RB, CY-RB, CX+RB, CY+RB)
chk("find", 40, find_y, DW-40, find_y+72)
save(img, "新结构_01_首页")

# ============================================================
# 屏 2 · 按住中（录音态）
# ============================================================
img, d = newpage()
d.rectangle([0, 0, W, px(56)], fill=BG); statusbar(d)
topbar(d, "想说啥就说啥")
text(d, (DW/2, 132), "正在听您说…", F(17), PRIMARY_D, "mm")

CX, CY, RB = DW/2, 330, 118
for i, r in enumerate([RB+46, RB+30, RB+16]):
    circle(d, CX, CY, r, fill=None, outline=["#F2D3B4", "#F6E0C9", "#FAEEDF"][i], width=3)
circle(d, CX, CY, RB, fill=PRIMARY_D)
icon(d, CX, CY-26, 44, "mic", color="#FFFFFF", lw=5.2)
text(d, (CX, CY+52), "00:07", F(22), "#FFFFFF", "mm")
text(d, (CX, CY+RB+36), "松手就停，说完会自动存下来", F(13), INK2, "mm")

# 实时转写气泡（让老人看到“它在记”）
rrect(d, [32, 588, DW-32, 700], 18, fill="#FFFFFF", outline=LINE, width=1.5)
text(d, (50, 604), "正在记下来：", F(11), GOLD)
text(d, (50, 626), "我们家一共三个孩子，我是老二，", F(14), INK)
text(d, (50, 650), "那时候家里穷，但爹妈都让我们念书…", F(14), INK)
chk("rec", CX-RB-46, CY-RB-46, CX+RB+46, CY+RB+46)
chk("bubble", 32, 588, DW-32, 700)
save(img, "新结构_02_按住中")

# ============================================================
# 屏 3 · 说完之后（弹层）—— 三件事：看 / 发 / 存+整理
# ============================================================
img, d = newpage()
d.rectangle([0, 0, W, px(56)], fill=BG); statusbar(d)
topbar(d, "想说啥就说啥")

# 背景压暗（弹层浮在上面的感觉）
ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
od = ImageDraw.Draw(ov)
od.rectangle([0, 0, W, H], fill=(58, 50, 44, 90))
img = Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")
d = ImageDraw.Draw(img)

SH_Y = 214
rrect(d, [14, SH_Y, DW-14, DH-14], 26, fill="#FFFDF9")
# 抓手
rrect(d, [DW/2-20, SH_Y+12, DW/2+20, SH_Y+17], 3, fill="#E4D9CB")

text(d, (36, SH_Y+34), "这段存好了", F(21), INK)
text(d, (36, SH_Y+66), "刚说了 1 分 12 秒 · 存进「我的故事」了", F(12), INK2)

# —— 大头：这段说成了什么（预览卡）
rv = [36, SH_Y+96, DW-36, SH_Y+96+150]
rrect(d, rv, 16, fill=CHIP)
rrect(d, [rv[0]+14, rv[1]+14, rv[0]+92, rv[1]+92], 10, fill="#FFFFFF", outline="#E7D9C6", width=1.5)
icon(d, rv[0]+53, rv[1]+53, 17, "photo", color="#C9B9A4", lw=2.6)
text(d, (rv[0]+110, rv[1]+18), "我出生在1973年", F(17), INK)
text(d, (rv[0]+110, rv[1]+48), "我们家一共三个孩子，我是老二，", F(12.5), INK2)
text(d, (rv[0]+110, rv[1]+70), "那时候家里穷，但爹妈都让我们", F(12.5), INK2)
text(d, (rv[0]+110, rv[1]+92), "念书…", F(12.5), INK2)
rrect(d, [rv[0]+110, rv[1]+118, rv[0]+110+74, rv[1]+142], 12, fill="#FFFFFF")
text(d, (rv[0]+147, rv[1]+130), "点开看全文", F(10.5), PRIMARY_D, "mm")
chk("preview", rv[0], rv[1], rv[2], rv[3])

# —— 一行三个：发送 / 做成图 / 整理成书  （平级，同大同形）
BY = SH_Y + 96 + 150 + 22
BW_ = (DW - 36*2 - 12*2) / 3
labels = [("send", "发出去", "微信/群里", TEAL), ("photo", "做成一张图", "能打印", GOLD), ("book", "整理成书", "这一辈子", GREEN)]
for i, (ic, t1, t2, col) in enumerate(labels):
    x = 36 + i*(BW_+12)
    b = [x, BY, x+BW_, BY+104]
    rrect(d, b, 16, fill="#FFFFFF", outline=LINE, width=1.5)
    circle(d, x+BW_/2, BY+36, 20, fill=col+"22" if False else "#F5F1EA")
    icon(d, x+BW_/2, BY+36, 15, ic, color=col, lw=2.6)
    text(d, (x+BW_/2, BY+66), t1, F(13.5), INK, "mm")
    text(d, (x+BW_/2, BY+86), t2, F(10.5), INK2, "mm")
    chk(f"act{i}", b[0], b[1], b[2], b[3])

# —— 底部一句话：继续 / 先不看
cb = [36, DH-108, DW-36, DH-48]
rrect(d, cb, 26, fill=PRIMARY)
text(d, (DW/2, DH-78), "再说一段", F(18), "#FFFFFF", "mm")
text(d, (DW/2, DH-28), "先不看，回头在「我的故事」里找", F(11.5), INK2, "mm")
chk("cont", cb[0], cb[1], cb[2], cb[3])
save(img, "新结构_03_说完之后")

# ============================================================
# 屏 4 · 原来的三个入口去了哪（对照说明页）
# ============================================================
img, d = newpage()
d.rectangle([0, 0, W, px(56)], fill=BG); statusbar(d)
topbar(d, "三个入口没取消，都收进来了")

text(d, (22, 132), "以前首页并排三个块，老人挑不出该点哪个；", F(12.5), INK2)
text(d, (22, 152), "现在一律从「我要说」进，说完再让他挑。", F(12.5), INK2)

items = [
    ("自己说 → 就是首页那个大圆", "原来要选入口，现在按住就说，不用选", PRIMARY, "mic"),
    ("找人说 → 大圆下面那个按钮", "采访时它问一句您说一句，跟聊天一样", TEAL, "users"),
    ("看 & 整理 → 说完之后的弹层", "说完整理成书/做图/发出去，都在那一步", GOLD, "book"),
]
y = 196
for t1, t2, col, ic in items:
    b = [22, y, DW-22, y+108]
    rrect(d, b, 18, fill="#FFFFFF", outline=LINE, width=1.5)
    rrect(d, [b[0], b[1], b[0]+7, b[3]], 3, fill=col)
    circle(d, b[0]+46, b[1]+54, 22, fill="#F5F1EA")
    icon(d, b[0]+46, b[1]+54, 16, ic, color=col, lw=2.7)
    text(d, (b[0]+82, b[1]+28), t1, F(14.5), INK)
    text(d, (b[0]+82, b[1]+58), t2, F(11.5), INK2)
    chk("i", b[0], b[1], b[2], b[3])
    y += 122

text(d, (22, y+16), "底部 4 个 tab 不动：首页 / 我的故事 / 时间轴 / 家里人", F(11.5), INK2)
tabbar(d, 0)
save(img, "新结构_04_入口搬家对照")

print("\n越界问题：", issues if issues else "无")
