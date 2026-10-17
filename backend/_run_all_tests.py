import subprocess, os
os.chdir("/home/ubuntu/echoes/backend")
tests = [
    "selftest_story_clip_perm.py",
    "selftest_collect_api.py",
    "selftest_claim.py",
    "selftest_collect_av.py",
    "selftest_login.py",
    "selftest_story_api.py",
    "selftest_e2e.py",
    "selftest_timeline_api.py",
    "selftest_anchor_api.py",
    "selftest_interview_api.py",
    "selftest_provenance.py",
    "selftest_book_api.py",
    "selftest_share_api.py",
    "selftest_payment_api.py",
    "selftest_interview_recap.py",
    "selftest_book_view.py",
    "selftest_storage_api.py",
    "selftest_tts_api.py",
    "selftest_join_api.py",
    "selftest_family_api.py",
    "selftest_group_api.py",
    "selftest_entitlement.py",
    "selftest_print_api.py",
]
tot_p = tot_f = 0
for t in tests:
    r = subprocess.run(["/usr/bin/python3", t], capture_output=True, text=True, timeout=300)
    out = r.stdout + r.stderr
    line = [l for l in out.splitlines() if "通过" in l or "结果" in l]
    summ = line[-1] if line else "(no summary)"
    status = "OK" if r.returncode == 0 else "FAIL"
    print(f"[{status}] {t}: {summ}  (exit={r.returncode})")
    if r.returncode != 0:
        print("    ---- tail ----")
        for l in out.splitlines()[-12:]:
            print("    " + l)
