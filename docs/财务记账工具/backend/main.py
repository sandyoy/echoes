"""
财务记账工具 — FastAPI 后端服务
"""
import os
import json
import secrets
import hashlib
from datetime import datetime
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Depends, status, Request
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import uvicorn

from bill_parser import BillParser
from database import init_db, create_user, get_user, save_bill, save_transactions
from database import get_bills, get_summary, get_transactions, delete_bill

# ---------- 简单的密码哈希（后续可升级为bcrypt） ----------
def hash_password(password: str) -> str:
    salt = "finance_tool_salt_2026"  # 固定盐，简化处理
    return hashlib.sha256((password + salt).encode()).hexdigest()

# ---------- Session 管理 ----------
# 简化的内存session（重启后需重新登录）
_sessions = {}  # token -> user_id

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(BASE_DIR, "..", "frontend")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # 确保默认管理员账号存在
    admin = get_user("admin")
    if not admin:
        create_user("admin", hash_password("admin123"), "管理员")
    yield


app = FastAPI(title="财务记账工具", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- 工具函数 ----------
def get_current_user(request: Request) -> int:
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not token or token not in _sessions:
        raise HTTPException(status_code=401, detail="未登录")
    return _sessions[token]


# ---------- 用户认证 API ----------
@app.post("/api/login")
async def login(username: str = Form(...), password: str = Form(...)):
    user = get_user(username)
    if not user or user["password_hash"] != hash_password(password):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = secrets.token_hex(32)
    _sessions[token] = user["id"]
    return {"token": token, "user_id": user["id"], "display_name": user["display_name"]}


@app.post("/api/register")
async def register(username: str = Form(...), password: str = Form(...),
                   display_name: str = Form("")):
    user_id = create_user(username, hash_password(password), display_name)
    if user_id == -1:
        raise HTTPException(status_code=400, detail="用户名已存在")
    return {"user_id": user_id, "message": "注册成功"}


# ---------- 账单上传与解析 API ----------
@app.post("/api/upload")
async def upload_bill(file: UploadFile = File(...), token: str = Form(...)):
    if token not in _sessions:
        raise HTTPException(status_code=401, detail="未登录")
    user_id = _sessions[token]

    # 保存上传文件
    upload_dir = os.path.join(BASE_DIR, "data", "uploads", str(user_id))
    os.makedirs(upload_dir, exist_ok=True)
    filepath = os.path.join(upload_dir, file.filename)
    content = await file.read()
    with open(filepath, "wb") as f:
        f.write(content)

    # 解析
    parser = BillParser()
    try:
        if file.filename.endswith(".xlsx"):
            tx = parser.parse_wechat_xlsx(filepath)
        else:
            raise HTTPException(status_code=400, detail="暂只支持 .xlsx 格式（微信账单）")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"解析失败: {str(e)}")

    if not tx:
        raise HTTPException(status_code=400, detail="未解析到任何交易记录")

    # 获取期间
    times = [t["time"] for t in tx if t["time"]]
    period_start = min(times) if times else ""
    period_end = max(times) if times else ""

    # 汇总
    income = sum(t["amount"] for t in tx if t["io"] == "收入")
    expense = sum(t["amount"] for t in tx if t["io"] == "支出")
    income_cnt = sum(1 for t in tx if t["io"] == "收入")
    expense_cnt = sum(1 for t in tx if t["io"] == "支出")

    # 保存到数据库
    source = "wechat" if "微信" in file.filename or file.filename.endswith(".xlsx") else "未知"
    bill_id = save_bill(user_id, file.filename, source, period_start, period_end,
                        income, expense, income_cnt, expense_cnt)
    save_transactions(bill_id, user_id, tx)

    return {
        "bill_id": bill_id,
        "period": {"start": period_start, "end": period_end},
        "total_income": round(income, 2),
        "total_expense": round(expense, 2),
        "income_count": income_cnt,
        "expense_count": expense_cnt,
        "records": len(tx),
        "message": "解析成功"
    }


# ---------- 数据查询 API ----------
@app.get("/api/summary")
async def api_summary(request: Request):
    user_id = get_current_user(request)
    return get_summary(user_id)


@app.get("/api/bills")
async def api_bills(request: Request):
    user_id = get_current_user(request)
    return {"bills": get_bills(user_id)}


@app.get("/api/transactions")
async def api_transactions(request: Request,
                           category: str = None, month: str = None,
                           io: str = None, limit: int = 500, offset: int = 0):
    user_id = get_current_user(request)
    return {"transactions": get_transactions(user_id, category, month, io, limit, offset)}


@app.delete("/api/bills/{bill_id}")
async def api_delete_bill(bill_id: int, request: Request):
    user_id = get_current_user(request)
    if delete_bill(bill_id, user_id):
        return {"message": "删除成功"}
    raise HTTPException(status_code=404, detail="账单不存在")


# ---------- 静态文件服务 ----------
@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return f.read()
    return HTMLResponse("<h1>财务记账工具</h1><p>请部署前端文件到 frontend/ 目录</p>")


# 如果前端目录存在，挂载静态文件
if os.path.exists(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")


# ---------- 启动 ----------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8008))
    host = os.environ.get("HOST", "0.0.0.0")
    print(f"启动财务记账工具... http://{host}:{port}")
    uvicorn.run("main:app", host=host, port=port, reload=False)
