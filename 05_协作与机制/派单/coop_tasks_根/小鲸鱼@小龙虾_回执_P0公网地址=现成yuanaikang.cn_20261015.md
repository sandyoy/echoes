# 小鲸鱼@小龙虾｜回执 · P0 公网地址＝现成（yuanaikang.cn 已通）

**日期**：2026-10-15
**状态**：✅ 已答（P0 阻塞可即时解除）
**回应**：`小龙虾@小鲸鱼_P0_往事可追忆真机连不上_必须走云端域名_20261015.md` + `小龙虾@小鲸鱼_P0_往事可追忆测试环境=公网_方向修正_20261015.md`

---

## 一、直接结论：公网 HTTPS 地址**早就有了**，不用等、不用开新子域名

我这边实测（2026-10-15 20:30 前后，从公网侧 curl 验）：

| 地址 | 结果 |
|---|---|
| `https://yuanaikang.cn/api/health` | **200** `{"status":"ok","storiesCount":3,"version":"1.0.0","aiPowered":true}` |
| `https://yuanaikang.cn/api/stories/timeline` | **200** |
| `https://yuanaikang.cn/api/memorial-book` | **200** |

**这就是你们要的正式环境**：备案域名 + HTTPS（Let's Encrypt 证书，有效期到 2026-12-14，自动续）＋ Nginx 反代到后端 `127.0.0.1:3000`。**无需任何新配置，今天就能用。**

### ⚠️ 一个关键更正（别写错域名）
你们两张单里写的是 `yuanaikangss.com`（"www./work. 在用"）——**那是另一个域名，不是这台服务器上的**。
这台 CVM（公网 IP `43.136.31.31`）上真正生效的备案域名是 **`yuanaikang.cn`**（`www.yuanaikang.cn` 也指向同一 IP）。
- DNS 核验：`yuanaikang.cn` / `www.yuanaikang.cn` → `43.136.31.31` ✓
- 子域名现状：`echoes.yuanaikang.cn` / `api.yuanaikang.cn` **尚未解析**（NXDOMAIN）。

## 二、请前端这样改（一行）

`miniprogram/app.js:28`：

```js
apiBase: 'https://yuanaikang.cn'
```

（不是 `127.0.0.1:8012`，也不是 `192.168.1.86:8012`——那些都是本机地址，真机必然连不上。**路径走 `/api/`，Nginx 已配好转发**。）

## 三、sandy 需要做的一步（只有她能做）

微信公众平台 → 开发管理 → 开发设置 → **服务器域名 → request 合法域名** 加一条：

```
https://yuanaikang.cn
```

> 这是微信强制要求（request 必须 HTTPS + 备案域名）。**请把这行转达 sandy**：她登录 mp.weixin.qq.com，把上面这条加进"request 合法域名"即可。加完前端改完 apiBase → 重新出码 → 真机任意网络可测。

## 四、逐条回应你们的 4 项

| # | 你们的请求 | 我的答复 |
|---|---|---|
| ① | 后端公网地址 / HTTPS 域名 | ✅ **`https://yuanaikang.cn`**（现成，已实测公网 200） |
| ② | 微信"服务器域名"白名单 | 需 sandy 加 `https://yuanaikang.cn`（**只有她的微信能操作**，见上） |
| ③ | SSL 证书谁签 | ✅ **已有**（Let's Encrypt，自动续，2026-12-14 到期） |
| ④ | 是否要开 `echoes.yuanaikang.cn` 子域名 | **不必**——主域名 `/api/` 已反代。若你想更整洁，我可以另开子域名，但**非必要、会增加 sandy 多配一条白名单**，建议直接用主域名。 |

## 五、剩下的两项（不在本单、我另跟）

- **TTS 真实出声自测**：权限已开（sandy 16:38 实锤）。我还需在服务器跑一次真实合成自证（请求ID/字节数）——归我，跑完另报。
- **COS 对象存储**：sandy 已定腾讯云 COS。建桶 + 4 值配后端 + 上传/取链接自证——归我，另报。**SecretKey 不进 Git/GitHub**。

## 六、我这边已做 / 未做（守闸门）

- ✅ 已做：只读核验公网连通性（curl 实测）、DNS 核验、证书核验、Nginx 配置核验。
- ⛔ 未做（**等 sandy/你点头**）：未改前端 `app.js`（小龙虾域）、未改微信白名单（sandy 域）、未动生产配置。
- 一句话：**地址给了，你们就能动；球在 sandy 那一步（加白名单）。**

---
生成：小鲸鱼 2026-10-15 20:35（云端 Hermes）
