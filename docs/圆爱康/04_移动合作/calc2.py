
# -*- coding: utf-8 -*-
HOSPITALS = [
    ("珠海市人民医院", 175.0, "综合三甲，13科室全落地", "估算：按1686开放床位/省级区域医疗中心规模反推（官方未公开年门诊量）"),
    ("珠海市妇幼保健院", 148.0, "专科，妇/产/生殖/儿4科室", "2023年近145万人次、出院4.71万（珠海市政府门户网站）；2024年150万人次（百度百科）"),
]
ZH = {
"珠海市人民医院": [
 ("妇科（含盆底）",   0.06, 5.0, 0.15, "盆底15%（sandy已验证）",      3800),
 ("产科/产后",       0.05, 6.0, 0.10, "产后居家估算（50%不去月子中心x10%选居家约5%，预留上限）", 4200),
 ("生殖医学科",      0.03, 5.0, 0.20, "生殖比例偏高（sandy判断）",     5600),
 ("心内科",          0.07, 4.0, 0.00, "管线推进中，本测算不含此项收入",   0),
 ("康复科",          0.04, 8.0, 0.03, "1%~5%取中（sandy判断）",       2980),
 ("神经内科",        0.06, 6.0, 0.10, "估算（sandy建议10%）",         4600),
 ("儿童心理/儿保",    0.04, 4.0, 0.05, "估算（sandy建议5%）",          3200),
 ("肛肠科",          0.03, 3.0, 0.03, "1%~5%取中（sandy判断）",       2600),
 ("骨科/疼痛",       0.08, 6.0, 0.02, "1%~5%取下沿（sandy判断）",      3400),
 ("泌尿外科",        0.04, 4.0, 0.02, "1%~5%取下沿",                3600),
],
"珠海市妇幼保健院": [
 ("妇科（含盆底）",   0.10, 5.0, 0.15, "盆底15%（sandy已验证）",      3800),
 ("产科/产后",       0.12, 6.0, 0.10, "产后居家估算",               4200),
 ("生殖医学科",      0.06, 5.0, 0.20, "生殖比例偏高（sandy判断）",     5600),
 ("儿童心理/儿保",    0.05, 4.0, 0.05, "估算（sandy建议5%）",          3200),
],
}
MOBILE_CUT=0.10
tot={}
out=[]
for name, wan, desc, src in HOSPITALS:
    out.append("="*78)
    out.append("【%s】%s" % (name, desc))
    out.append("年门诊量 %.0f 万人次 ｜ 来源：%s" % (wan, src))
    out.append("-"*78)
    out.append("%-14s %9s %8s %9s %9s %11s" % ("科室","门诊人次(万)","人均次数","患者人数","签约人数","年流水(万)"))
    tp=0; tr=0
    for d,share,per,conv,basis,price in ZH[name]:
        visits=wan*share
        heads=visits*10000/per
        signed=heads*conv
        rev=signed*price/10000
        tp+=signed; tr+=rev
        out.append("%-14s %9.1f %8.1f %9.0f %9.0f %11.1f" % (d,visits,per,heads,signed,rev))
    out.append("-"*78)
    out.append("%-14s %9s %8s %9s %9.0f %11.1f" % ("合计","","","",tp,tr))
    out.append("-> 移动按10%%分成：%.0f 万元/年" % (tr*MOBILE_CUT))
    tot[name]=(tp,tr)
    out.append("")
out.append("="*78)
out.append("【两家合计】")
tp=sum(v[0] for v in tot.values()); tr=sum(v[1] for v in tot.values())
for k,v in tot.items():
    out.append("  %-14s 签约 %6.0f 人 ｜ 年流水 %8.0f 万元 ｜ 移动分成 %6.0f 万元" % (k,v[0],v[1],v[1]*MOBILE_CUT))
out.append("  %-14s 签约 %6.0f 人 ｜ 年流水 %8.0f 万元 ｜ 移动分成 %6.0f 万元" % ("合计",tp,tr,tr*MOBILE_CUT))
out.append("")
avg=tr/2
out.append("【广东盘子】按可复制同类型医院 40 家（综合25家+妇幼15家）")
out.append("  年流水 约 %.1f 亿元 ｜ 移动分成 约 %.0f 万元/年（%.2f 亿元）" % (avg*40/10000, avg*40*MOBILE_CUT, avg*40*MOBILE_CUT/10000))
out.append("  40家=假设渗透率（广东三甲约200家），实际按移动集客覆盖铺开")
print("\n".join(out))
