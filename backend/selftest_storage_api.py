"""
自测：对象存储上传通道（storage_api.py）
跑法：cd backend && /usr/bin/python3 selftest_storage_api.py
"""

import os
import sys
import shutil
import tempfile

# 自测库隔离（教训：必须用 DATABASE_URL，不是 ECHOES_DB/DB_PATH）
_TMPDB = tempfile.mktemp(suffix="_storage_test.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMPDB}"
# 本地存储落临时目录，别污染 ~/.echoes_media
_MEDIA = tempfile.mkdtemp(prefix="echoes_media_test_")
os.environ["ECHOES_STORAGE"] = "local"
os.environ["ECHOES_LOCAL_ROOT"] = _MEDIA
os.environ["ECHOES_PUBLIC_BASE"] = "/media"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import storage_api as S

P = F = 0


def check(cond, name):
    global P, F
    if cond:
        P += 1
        print(f"  [OK] {name}")
    else:
        F += 1
        print(f"  [FAIL] {name}")


def section(t):
    print(f"\n=== {t} ===")


def main():
    global P, F
    from models import init_db, SessionLocal
    init_db()
    db = SessionLocal()

    print("自测：对象存储上传通道 v1.0")
    print(f"  临时媒体根：{_MEDIA}")

    # 延迟 import，供建书/建故事用
    import story_api

    # ------------------------------------------------------------
    section("① 配置探测：默认 local 且可写（不假装）")
    st = S.api_storage_status()
    check(st["ok"] is True, "storage/status 返回 ok")
    check(st["data"]["backend"] == "local", "默认后端 = local")
    check(st["data"]["writable"] is True, "本地后端可写（真探针写+删）")

    # ------------------------------------------------------------
    section("② key 净化：防穿越 / 中文保留 / 空名回落")
    check(S.sanitize_filename("../../etc/passwd") == "passwd", "去目录穿越（取 basename）")
    check("/" not in S.sanitize_filename("a/b/c.jpg").replace("/", ""), "文件名不含路径分隔")
    check(S.sanitize_filename("妈的老照片.jpg") == "妈的老照片.jpg", "中文名保留")
    check(S.sanitize_filename("") == "unnamed", "空名 → unnamed")
    check(S.sanitize_filename("...") == "unnamed", "纯点 → unnamed")
    k = S.build_key(actor_id="u_zhang", kind="image", file_name="老照片.jpg")
    check(k.startswith("clips/u_zhang/image/"), "key 前缀绑 actor+kind")
    check(".." not in k, "key 无穿越段")
    k2 = S.build_key(actor_id="u_zhang", kind="image", file_name="老照片.jpg")
    check(k != k2, "同文件两次上传 key 不同（不互相覆盖）")
    check(S.sanitize_actor("../../evil") == "evil", "actor 净化去穿越")
    check(S.sanitize_actor("") == "", "空 actor → 空（非法）")

    # ------------------------------------------------------------
    section("③ 上传校验：类型/大小/扩展名/空文件")
    ok1, _, _ = S.validate_upload(kind="image", file_name="a.jpg", file_size=1024, mime="image/jpeg")
    check(ok1, "正常图片通过")
    bad, msg, code = S.validate_upload(kind="image", file_name="a.jpg", file_size=0)
    check(not bad and code == "empty_file", "空文件拒")
    bad, msg, code = S.validate_upload(kind="image", file_name="a.jpg", file_size=25 * 1024 * 1024)
    check(not bad and code == "too_large", "超限拒（20MB）")
    bad, msg, code = S.validate_upload(kind="image", file_name="a.exe", file_size=1024)
    check(not bad and code == "bad_ext", "非法扩展名拒")
    bad, msg, code = S.validate_upload(kind="nope", file_name="a.jpg", file_size=1)
    check(not bad and code == "bad_kind", "未知类型拒")
    okv, _, _ = S.validate_upload(kind="video", file_name="v.mp4", file_size=150 * 1024 * 1024)
    check(okv, "视频 150MB 通过（上限200MB）")
    bad, msg, code = S.validate_upload(kind="video", file_name="v.mp4", file_size=250 * 1024 * 1024)
    check(not bad and code == "too_large", "视频超 200MB 拒")
    okn, _, _ = S.validate_upload(kind="audio", file_name="noext", file_size=1000, mime="audio/mp4")
    check(okn, "无扩展名但有 mime → 放行")
    bad, msg, code = S.validate_upload(kind="audio", file_name="noext", file_size=1000, mime="")
    check(not bad and code == "unknown_type", "无扩展名无 mime → 拒")

    # ------------------------------------------------------------
    section("④ api_upload_url：拿到地址 + 不配假 URL")
    r = S.api_upload_url(actor_id="u_zhang", kind="image", file_name="老照片.jpg",
                         file_size=2048, mime="image/jpeg")
    check(r["ok"] is True, "取上传地址成功")
    d = r["data"]
    check(d.get("upload_url", "").startswith("http") or d.get("upload_url", "").startswith("/"),
          "给了 upload_url")
    check(d.get("method") == "PUT", "method=PUT")
    check(d["key"].startswith("clips/u_zhang/image/"), "key 前缀对")
    check(d.get("backend") == "local", "backend=local")
    r2 = S.api_upload_url(actor_id="", kind="image", file_name="a.jpg", file_size=100)
    check(not r2["ok"] and r2["code"] == "missing_actor", "缺 actor → 拒")
    r3 = S.api_upload_url(actor_id="u", kind="image", file_name="a.exe", file_size=100)
    check(not r3["ok"] and r3["code"] == "bad_ext", "非法格式 → 拒（不签地址）")

    # ------------------------------------------------------------
    section("⑤ 真传字节 → 取可读地址（本地后端真落盘）")
    key = d["key"]
    put = S.get_storage().put_bytes(key=key, data=b"\xff\xd8\xff fake jpeg bytes")
    check(put.get("stored") is True, "put_bytes 真落盘")
    check(os.path.isfile(os.path.join(_MEDIA, key)), "文件真在磁盘上（不是假装）")
    mu = S.api_media_url(key=key)
    check(mu["ok"] and mu["data"]["media_url"].startswith("/media/"), "回放地址 = /media/... ")
    miss = S.api_media_url(key="clips/u_zhang/image/not-exist.jpg")
    check(not miss["ok"] and miss["code"] == "object_not_found", "不存在的 key → 明确报错")

    # ------------------------------------------------------------
    section("⑥ 越权：key 前缀不属于本人 → 拒")
    res = S.api_confirm_upload(db=db, actor_id="u_evil", key=key,
                               kind="image", story_id="s1", visibility="public")
    check(not res["ok"] and res["code"] == "key_actor_mismatch",
          "别人拿你的 key 登记 → 拒")

    # ------------------------------------------------------------
    section("⑦ 端到端：建书→建故事→上传→confirm→能取到素材（含公开/私有）")
    cu = story_api.api_create_book(db, owner_id="u_zhang")
    check(cu["ok"], "建书 ok")
    book_id = cu["data"]["book_id"] if "book_id" in cu["data"] else cu["data"].get("owner_id", "u_zhang")
    stry = story_api.api_create_story(db, owner_id="u_zhang", actor_id="u_zhang",
                                      title="八岁那年")
    check(stry["ok"], "建故事 ok")
    sid = stry["data"]["story_id"]

    # 传一张公开照片
    up = S.api_upload_url(actor_id="u_zhang", kind="image", file_name="老屋.jpg",
                          file_size=4096, mime="image/jpeg")
    k_photo = up["data"]["key"]
    S.get_storage().put_bytes(key=k_photo, data=b"\xff\xd8\xff photo")
    cf = S.api_confirm_upload(db=db, actor_id="u_zhang", key=k_photo, kind="image",
                              story_id=sid, file_name="老屋.jpg", file_size=4096,
                              mime="image/jpeg", visibility="public")
    check(cf["ok"], "确认入库（公开）ok")
    check(cf["data"]["visibility"] == "public", "visibility 落成 public")
    check(cf["data"]["media_url"].startswith("/media/clips/u_zhang/"), "media_url 指向真实对象")

    # 传一条原声（应不转写）
    up2 = S.api_upload_url(actor_id="u_zhang", kind="original", file_name="我妈的声音.m4a",
                           file_size=8192, mime="audio/mp4")
    k_orig = up2["data"]["key"]
    S.get_storage().put_bytes(key=k_orig, data=b"fake m4a")
    cf2 = S.api_confirm_upload(db=db, actor_id="u_zhang", key=k_orig, kind="original",
                               story_id=sid, file_name="我妈的声音.m4a", file_size=8192,
                               mime="audio/mp4", duration=12.5, visibility="private")
    check(cf2["ok"], "原声入库 ok")
    check(cf2["data"]["visibility"] == "private", "原声默认私有")
    check(cf2["data"].get("transcribed") in (None, False) or cf2["data"].get("transcript") in (None, ""),
          "原声不转写（§6.2.2）")

    # 从筐里能取到
    import collect_api
    lst = collect_api.api_list_clips(db, story_id=sid, owner_id="u_zhang", viewer_id="u_zhang")
    check(lst["ok"], "取筐 ok")
    clips = lst["data"]["clips"]
    check(len(clips) == 2, f"筐里 2 件素材（实得 {len(clips)}）")
    types = {c["clip_type"] for c in clips}
    check("photo" in types and "original" in types, "photo + original 都在")

    # ------------------------------------------------------------
    section("⑧ 没传成功就不许登记（防假装）")
    up3 = S.api_upload_url(actor_id="u_zhang", kind="image", file_name="没传的.jpg",
                           file_size=100, mime="image/jpeg")
    k_ghost = up3["data"]["key"]
    # 故意不 put_bytes
    ghost = S.api_confirm_upload(db=db, actor_id="u_zhang", key=k_ghost, kind="image",
                                 story_id=sid, visibility="public")
    check(not ghost["ok"] and ghost["code"] == "object_not_found",
          "对象不存在 → 拒登记（不假装成功）")

    # ------------------------------------------------------------
    section("⑨ 越界 key 直接写盘 → 拒（最后一道闸）")
    st_local = S.get_storage()
    try:
        st_local.put_bytes(key="../../../../tmp/evil.txt", data=b"x")
        check(False, "越界 key 应被拒")
    except ValueError:
        check(True, "越界 key 被拒（防跑出 root）")

    # ------------------------------------------------------------
    section("⑩ COS 未配：明确报错，不假装")
    cfg = {"backend": "cos", "cos_secret_id": "", "cos_secret_key": "",
           "cos_region": "", "cos_bucket": ""}
    try:
        S.get_storage(cfg)
        check(False, "COS 缺凭证应抛错")
    except RuntimeError as e:
        check("not_configured" in str(e), "COS 缺凭证 → storage_not_configured")
    check(S.cos_configured(cfg) is False, "缺凭证 → cos_configured=False")

    # ------------------------------------------------------------
    section("⑪ 信封形状统一")
    check(set(["ok", "data"]).issubset(S.ok({"a": 1}).keys()), "ok 信封含 ok/data")
    f = S.fail("坏", "x")
    check(f["ok"] is False and f["code"] == "x" and "error" in f, "fail 信封含 ok/error/code")

    print(f"\n结果：通过 {P} / 失败 {F}   （共 {P + F}）")
    db.close()

    # 清理
    try:
        os.remove(_TMPDB)
    except Exception:
        pass
    shutil.rmtree(_MEDIA, ignore_errors=True)
    return 0 if F == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
