"""
账单解析引擎 — 支持微信支付账单(.xlsx)
扩展：支付宝(.csv)、银行(.csv) 可后续添加
"""
import re
import openpyxl
from datetime import datetime
from typing import List, Dict, Optional


class BillParser:
    """微信支付账单解析器"""

    CATEGORY_RULES = [
        # 餐饮
        (["美团", "饿了么", "外卖", "餐饮", "美食", "餐厅", "客家菜", "遇见小面",
          "麦当劳", "肯德基", "星巴克", "奶茶", "咖啡", "食堂", "饭", "面", "餐",
          "水果", "生鲜", "买菜", "蔬菜", "超市"], "餐饮"),
        # 交通出行
        (["ETC", "高速", "加油", "充电", "停车", "打车", "滴滴", "出租车",
          "地铁", "公交", "高铁", "机票", "南网电动", "一嗨租车", "房车"], "交通出行"),
        # 购物消费
        (["淘宝", "天猫", "京东", "拼多多", "微信小店", "抖音", "视频号",
          "小店", "优选", "百货", "家居", "数码", "电器", "服饰", "饰品",
          "珠宝", "茶叶", "紫砂", "礼品"], "购物消费"),
        # 教育学习
        (["教育", "培训", "课程", "编程", "机器人", "学而思", "豌豆",
          "博商", "博佳", "京师之道", "学习", "大学", "学院"], "教育学习"),
        # 医疗健康
        (["医院", "医疗", "药房", "药品", "中药", "三得堂", "福仁康",
          "中医", "康复", "体检", "医保", "中山眼科", "孙逸仙"], "医疗健康"),
        # 生活服务
        (["家政", "阿姨", "物业", "水电", "燃气", "宽带", "话费",
          "手机充值", "中国移动", "联通", "电信", "快递", "邮政"], "生活服务"),
        # 保险金融
        (["保险", "人寿", "财产保险", "理财", "基金", "投资"], "保险金融"),
        # 转账（亲友往来）
        (["转账", "红包", "群收款"], "转账往来"),
        # 退款
        (["退款", "已退款"], "退款"),
    ]

    def __init__(self):
        self.transactions = []

    def parse_wechat_xlsx(self, filepath: str) -> List[Dict]:
        """解析微信支付账单 .xlsx 文件"""
        wb = openpyxl.load_workbook(filepath, read_only=True)
        ws = wb.active
        transactions = []

        for row in ws.iter_rows(min_row=19, values_only=True):
            if row[0] is None:
                continue
            v0 = str(row[0]).strip()
            if v0 == "" or v0.startswith("共") or v0.startswith("---"):
                continue

            try:
                tx_time = str(row[0])[:19]
                tx_type = str(row[1]) if row[1] else ""
                peer = str(row[2]) if row[2] else ""
                goods = str(row[3]) if row[3] else ""
                io_type = str(row[4]) if row[4] else "/"
                amount = float(row[5]) if row[5] else 0.0
                method = str(row[6]) if row[6] else ""
                status = str(row[7]) if row[7] else ""
            except (ValueError, TypeError):
                continue

            # 中性交易跳过（充值/提现/理财等）
            if io_type == "/":
                continue

            category = self._classify(tx_type, peer, goods, io_type)

            transactions.append({
                "time": tx_time,
                "type": tx_type,
                "peer": peer,
                "goods": goods,
                "io": io_type,  # "收入" or "支出"
                "amount": amount,
                "method": method,
                "status": status,
                "category": category,
                "month": tx_time[:7] if tx_time else "未知",
                "year": tx_time[:4] if tx_time else "未知",
            })

        wb.close()
        self.transactions = transactions
        return transactions

    def _classify(self, tx_type: str, peer: str, goods: str, io: str) -> str:
        """根据交易对方+商品描述+交易类型综合判断分类"""
        text = f"{tx_type} {peer} {goods}"

        # 退款单独处理
        if "退款" in tx_type or "退款" in goods or "已退款" in goods:
            return "退款"

        # 转账往来
        if tx_type in ["转账", "转账-退款"]:
            return "转账往来"
        if tx_type in ["微信红包", "微信红包（单发）", "微信红包（群红包）", "微信红包-退款"]:
            return "转账往来"
        if tx_type == "群收款":
            return "转账往来"

        # 扫码付款默认归为购物消费
        if tx_type in ["扫二维码付款", "二维码收款", "付款码付款"]:
            # 检查是否有指向性
            return "购物消费"

        # 商户消费 → 按关键词匹配
        for keywords, cat in self.CATEGORY_RULES:
            for kw in keywords:
                if kw in text:
                    return cat

        # 默认
        if io == "收入":
            return "其他收入"
        return "其他支出"

    def get_summary(self, transactions: Optional[List[Dict]] = None) -> Dict:
        """生成汇总数据"""
        tx = transactions or self.transactions

        total_income = sum(t["amount"] for t in tx if t["io"] == "收入")
        total_expense = sum(t["amount"] for t in tx if t["io"] == "支出")
        income_count = sum(1 for t in tx if t["io"] == "收入")
        expense_count = sum(1 for t in tx if t["io"] == "支出")

        # 按分类
        by_category = {}
        for t in tx:
            cat = t["category"]
            if cat not in by_category:
                by_category[cat] = {"收入": 0.0, "支出": 0.0, "count_income": 0, "count_expense": 0}
            by_category[cat][t["io"]] += t["amount"]
            if t["io"] == "收入":
                by_category[cat]["count_income"] += 1
            else:
                by_category[cat]["count_expense"] += 1

        # 按月
        by_month = {}
        for t in tx:
            m = t["month"]
            if m not in by_month:
                by_month[m] = {"收入": 0.0, "支出": 0.0}
            by_month[m][t["io"]] += t["amount"]

        # 按年
        by_year = {}
        for t in tx:
            y = t["year"]
            if y not in by_year:
                by_year[y] = {"收入": 0.0, "支出": 0.0}
            by_year[y][t["io"]] += t["amount"]

        return {
            "total_income": round(total_income, 2),
            "total_expense": round(total_expense, 2),
            "net": round(total_income - total_expense, 2),
            "income_count": income_count,
            "expense_count": expense_count,
            "by_category": by_category,
            "by_month": dict(sorted(by_month.items())),
            "by_year": dict(sorted(by_year.items())),
        }

    def get_big_expenses(self, threshold: float = 1000, transactions: Optional[List[Dict]] = None) -> List[Dict]:
        """获取大额支出"""
        tx = transactions or self.transactions
        return sorted(
            [t for t in tx if t["io"] == "支出" and t["amount"] >= threshold],
            key=lambda x: x["amount"], reverse=True
        )

    def get_monthly_detail(self, month: str, transactions: Optional[List[Dict]] = None) -> List[Dict]:
        """获取指定月份明细"""
        tx = transactions or self.transactions
        return [t for t in tx if t["month"] == month]
