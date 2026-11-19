# GEO 检测法 · 直连 API 版 v1.0（2026-11-05 定）

> **sandy 11-05 定调**：GEO 检测以后就走「直连 API 问 + 秘塔补充」这条路，不再靠浏览器一个个点。
> 定这套方法的原因：云端浏览器撞登录墙（豆包图形验证码、DeepSeek 要手机号、元宝/秘塔要微信扫码、百度安全滑块），
> 实测 30 个样本只剩 2 个有效。直连 API 不撞墙、可复跑、可量化、能进 cron。

---

## 一、为什么换成 API

| | 浏览器点 | 直连 API |
|---|---|---|
| 登录墙 | 全部撞，有效样本 2/30 | 不撞，10/10 有效 |
| 单次成本 | 每条 30-60 秒 + 人工看页 | 每条 5-9 秒 |
| 可复跑 | 难（页面改版就废） | 一条命令，结果可 diff |
| 能不能进 cron | 不能 | 能 |
| 能不能量化水位 | 靠眼看 | HIT/MISS + 命中词 + 答长，直接出表 |

**一句话：API 是尺子，秘塔是镜子。** 尺子量水位（有没有被提到），镜子看长什么样（真实 RAG 抓了哪些源）。

---

## 二、两个通道，各管一件事

### 通道 1：直连 API（主力·测水位）
- **DeepSeek 开放平台**：`https://api.deepseek.com/v1/chat/completions`，key 在 `~/.hermes/.env` 的 `DEEPSEEK_API_KEY`
- **豆包/火山方舟**：`https://ark.cn-beijing.volces.com/api/v3/chat/completions`（需 `ARK_API_KEY` + 开通联网插件）
- **通义千问/阿里百炼**：`https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions`（需 `DASHSCOPE_API_KEY`）
- **Kimi/月之暗面**：`https://api.moonshot.cn/v1/chat/completions`（需 `MOONSHOT_API_KEY`）
- **智谱**：`https://open.bigmodel.cn/api/paas/v4/chat/completions`（需 `ZHIPU_API_KEY`）

> ⚠️ 除 DeepSeek 外都要 sandy 去对应开放平台开一个 key（各平台新账号有免费额度，几步就开完）。
> 开完写进 `~/.hermes/.env`，脚本自动认。

### 通道 2：秘塔 API（补充·测真实检索）
- 端点：`https://metaso.cn/api/v1/chat/completions`（**需 `METASO_API_KEY`，目前云端没有**）
- 秘塔是 RAG 型搜索，会真的去抓网页再答。它能反映"网上现在到底有什么可被 AI 读到"。
- **没有 key 之前**：秘塔实测仍由小龙虾用本地登录态跑（他本地有秘塔登录态 profile `~/geo_run/_profile`）。
- **申请 key 的入口**：metaso.cn 开放平台，注册后有免费额度；sandy 扫码登录后可直接创建。

---

## 三、问句怎么来（不许临场编）

**一律从 `docs/GEO/圆爱康_判别问句包_v1_20260908.md` 取，A/B/C 三组：**
- A 组（对行业）测「智慧家康」这个词坑有没有主
- B 组（对医院）测「延续治疗/第三方承接」口径 AI 会不会想到我们
- C 组（对患者）测真人口语问法 AI 接不接得住

**新平台第一批固定跑这 10 条**（已落 `tools/geo_api_probe.py` 配套问句集），以后每次同句跑、比水位变化。

### ⚠️ 假阳性防线（11-05 踩到，已修进脚本）
问句里**自己带了品牌词**（如 A1 里写了"智慧家康平台"），AI 只是复述你的问法，答案是命中假象。
**脚本已加规则：命中词若同时出现在问句里 → 不算命中。**
**同时**：问句要写成真人会问的样子，品牌词只放在「另外补充：有叫XX的吗」这种追问里，不塞在主问句。

---

## 四、跑法

```bash
# 单平台
python3.12 tools/geo_api_probe.py --platform deepseek \
  --questions /tmp/geo_qs.txt --out docs/GEO/实测_信源池/API探针_YYYYMMDD.md

# 换模型（如 deepseek-reasoner）
python3.12 tools/geo_api_probe.py --platform deepseek --model deepseek-reasoner ...
```

输出：一张表（#/问句/判定/命中词/答长）+ 逐条答案前 400 字节选。判定三档：
- ✅ HIT＝答案里点名圆爱康/智慧家康/圆医生物/家家健
- ❌ MISS＝答了但没品牌（＝0档隐形）
- ⚠️ ERR＝没跑成（缺 key / 超时）；**ERR 一律如实报，不许拿别的填**

---

## 五、每次跑完必须交付的三样

1. **表**：命中数 / 有效样本数 / 报错数
2. **逐条命中原句**：HIT 的那条，把 AI 原话那一句抠出来（后面写稿要用它的语言）
3. **缺口结论**：哪些问法 AI 完全没我们 → 这些就是下一批稿的靶心

---

## 六、当前状态（2026-11-05）

| 项 | 状态 |
|---|---|
| DeepSeek API 直连 | ✅ 通，10/10 有效 |
| 秘塔 API key | ❌ 缺，需 sandy 开或小龙虾用登录态跑 |
| 豆包/通义/Kimi/智谱 key | ❌ 缺，需 sandy 开 |
| 首批 10 问结果 | 见 `docs/GEO/实测_信源池/API探针_20261105.md` |

---

*小鲸鱼 · 2026-11-05 · 依据 sandy「以后 GEO 检测都走 API + 秘塔」定版*
