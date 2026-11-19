/* 财务记账工具 — 前端逻辑 v2 */
const API_BASE = window.location.origin;
let token = localStorage.getItem('finance_token') || '';
let userDisplay = localStorage.getItem('finance_user') || '';
let categoryChart = null;
let trendChart = null;
let allTransactions = [];

// 检查是否已登录
if (token) {
    enterMain();
}

function enterMain() {
    document.getElementById('loginPage').style.display = 'none';
    document.getElementById('mainPage').style.display = 'block';
    document.getElementById('userDisplay').textContent = '👤 ' + userDisplay;
    loadDashboard();
}

// ========== 登录 ==========
document.getElementById('loginForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const username = document.getElementById('loginUsername').value;
    const password = document.getElementById('loginPassword').value;
    const errEl = document.getElementById('loginError');
    errEl.textContent = '登录中...';

    try {
        const formData = new FormData();
        formData.append('username', username);
        formData.append('password', password);
        const res = await fetch(API_BASE + '/api/login', { method: 'POST', body: formData });
        const data = await res.json();
        if (!res.ok) { errEl.textContent = data.detail; return; }
        token = data.token;
        userDisplay = data.display_name || username;
        localStorage.setItem('finance_token', token);
        localStorage.setItem('finance_user', userDisplay);
        enterMain();
    } catch(e) {
        errEl.textContent = '网络错误，请重试';
    }
});

function logout() {
    token = '';
    localStorage.removeItem('finance_token');
    localStorage.removeItem('finance_user');
    document.getElementById('mainPage').style.display = 'none';
    document.getElementById('loginPage').style.display = 'flex';
    document.getElementById('loginError').textContent = '';
}

// ========== 上传 ==========
function showUpload() { document.getElementById('uploadSection').style.display = 'block'; }
function hideUpload() { document.getElementById('uploadSection').style.display = 'none'; }

const dropZone = document.getElementById('dropZone');
dropZone.addEventListener('click', () => document.getElementById('fileInput').click());
dropZone.addEventListener('dragover', (e) => { e.preventDefault(); dropZone.classList.add('dragover'); });
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropZone.classList.remove('dragover');
    if (e.dataTransfer.files.length > 0) handleFile(e.dataTransfer.files[0]);
});
document.getElementById('fileInput').addEventListener('change', (e) => {
    if (e.target.files.length > 0) handleFile(e.target.files[0]);
});

async function handleFile(file) {
    if (!file.name.endsWith('.xlsx')) {
        showUploadResult('请上传 .xlsx 格式的微信账单文件', false);
        return;
    }
    showUploadProgress();
    try {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('token', token);
        const res = await fetch(API_BASE + '/api/upload', { method: 'POST', body: formData });
        const data = await res.json();
        if (!res.ok) { showUploadResult(data.detail || '解析失败', false); return; }
        showUploadResult(`✅ 解析成功！共 ${data.records} 条记录<br>
            收入: ¥${fmt(data.total_income)} (${data.income_count}笔)<br>
            支出: ¥${fmt(data.total_expense)} (${data.expense_count}笔)<br>
            时间: ${data.period.start} ~ ${data.period.end}`, true);
        loadDashboard();
    } catch(e) {
        showUploadResult('上传失败，请重试', false);
    }
}

function showUploadProgress() {
    document.getElementById('dropZone').style.display = 'none';
    document.getElementById('uploadProgress').style.display = 'block';
    document.getElementById('uploadResult').style.display = 'none';
}
function showUploadResult(msg, success) {
    document.getElementById('dropZone').style.display = 'block';
    document.getElementById('uploadProgress').style.display = 'none';
    const el = document.getElementById('uploadResult');
    el.style.display = 'block';
    el.className = 'upload-result ' + (success ? 'success' : 'error');
    el.innerHTML = msg;
}

// ========== 加载仪表盘 ==========
async function loadDashboard() {
    await Promise.all([loadSummary(), loadBills()]);
}

async function loadSummary() {
    try {
        const res = await fetch(API_BASE + '/api/summary', {
            headers: { 'Authorization': 'Bearer ' + token }
        });
        if (!res.ok) { if (res.status === 401) logout(); return; }
        const data = await res.json();

        document.getElementById('totalIncome').textContent = '¥' + fmt(data.total_income);
        document.getElementById('totalExpense').textContent = '¥' + fmt(data.total_expense);
        document.getElementById('netAmount').textContent = '¥' + fmt(data.net);
        document.getElementById('incomeCount').textContent = data.income_count + '笔';
        document.getElementById('expenseCount').textContent = data.expense_count + '笔';

        const netEl = document.getElementById('netAmount');
        netEl.style.color = data.net >= 0 ? 'var(--income)' : 'var(--expense)';

        renderCategoryChart(data.by_category);
        renderTrendChart(data.by_month);
    } catch(e) { console.error(e); }
}

async function loadBills() {
    try {
        const res = await fetch(API_BASE + '/api/bills', {
            headers: { 'Authorization': 'Bearer ' + token }
        });
        if (!res.ok) return;
        const data = await res.json();
        const el = document.getElementById('billList');
        if (!data.bills || data.bills.length === 0) {
            el.innerHTML = '<p class="empty-hint">暂无账单，上传第一份账单开始记账吧</p>';
            return;
        }
        el.innerHTML = data.bills.map(b => `
            <div class="bill-item">
                <div class="bill-info">
                    <div class="bill-name">📄 ${esc(b.filename)}</div>
                    <div class="bill-detail">
                        ${b.period_start || ''} ~ ${b.period_end || ''}
                        &nbsp;|&nbsp; 收入¥${fmt(b.total_income)} 支出¥${fmt(b.total_expense)}
                        &nbsp;|&nbsp; ${b.upload_time}
                    </div>
                </div>
                <button class="btn btn-sm btn-danger" onclick="deleteBill(${b.id})">删除</button>
            </div>
        `).join('');
    } catch(e) { console.error(e); }
}

async function deleteBill(billId) {
    if (!confirm('确定删除这份账单？')) return;
    const res = await fetch(API_BASE + '/api/bills/' + billId, {
        method: 'DELETE',
        headers: { 'Authorization': 'Bearer ' + token }
    });
    if (res.ok) loadDashboard();
}

// ========== 图表 ==========
let _categoryLabels = [];
let _monthLabels = [];

function renderCategoryChart(byCategory) {
    const ctx = document.getElementById('categoryChart').getContext('2d');
    if (categoryChart) categoryChart.destroy();

    const labels = [];
    const data = [];
    const colors = ['#4f6ef7','#22c55e','#ef4444','#f59e0b','#8b5cf6','#ec4899',
                    '#14b8a6','#f97316','#6366f1','#84cc16','#06b6d4','#a855f7'];

    Object.entries(byCategory)
        .filter(([_, v]) => v['支出'] > 0)
        .sort((a, b) => b[1]['支出'] - a[1]['支出'])
        .forEach(([cat, v], i) => {
            if (v['支出'] > 0) {
                labels.push(cat);
                data.push(Math.round(v['支出'] * 100) / 100);
            }
        });

    if (data.length > 8) {
        const main = data.slice(0, 7);
        const mainL = labels.slice(0, 7);
        let other = data.slice(7).reduce((a, b) => a + b, 0);
        main.push(Math.round(other * 100) / 100);
        mainL.push('其他');
        data.length = 0; labels.length = 0;
        data.push(...main); labels.push(...mainL);
    }

    _categoryLabels = labels;

    categoryChart = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: labels,
            datasets: [{
                data: data,
                backgroundColor: colors.slice(0, labels.length),
                borderWidth: 2, borderColor: '#fff',
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            onClick: (e, elements) => {
                if (elements.length > 0) {
                    const idx = elements[0].index;
                    const cat = _categoryLabels[idx];
                    if (cat && cat !== '其他') {
                        setFilter('category', cat);
                    }
                }
            },
            plugins: {
                legend: {
                    position: 'right',
                    labels: { font: { size: 12 }, padding: 12,
                        generateLabels: (chart) => {
                            const orig = Chart.defaults.plugins.legend.labels.generateLabels(chart);
                            orig.forEach(l => l.text = '🔍 ' + l.text);
                            return orig;
                        }
                    },
                    onClick: (e, legendItem, legend) => {
                        const idx = legendItem.index;
                        const cat = _categoryLabels[idx];
                        if (cat && cat !== '其他') {
                            setFilter('category', cat);
                        }
                    }
                },
                tooltip: {
                    callbacks: {
                        label: (ctx) => {
                            const total = ctx.dataset.data.reduce((a, b) => a + b, 0);
                            const pct = (ctx.parsed / total * 100).toFixed(1);
                            return `${ctx.label}: ¥${fmt(ctx.parsed)} (${pct}%)`;
                        }
                    }
                }
            }
        }
    });
}

function renderTrendChart(byMonth) {
    const ctx = document.getElementById('trendChart').getContext('2d');
    if (trendChart) trendChart.destroy();

    const months = Object.keys(byMonth).sort();
    _monthLabels = months;
    const incomes = months.map(m => byMonth[m]['收入']);
    const expenses = months.map(m => byMonth[m]['支出']);

    trendChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: months,
            datasets: [
                { label: '收入', data: incomes, backgroundColor: 'rgba(34,197,94,0.7)', borderColor: '#22c55e', borderWidth: 1, borderRadius: 4 },
                { label: '支出', data: expenses, backgroundColor: 'rgba(239,68,68,0.7)', borderColor: '#ef4444', borderWidth: 1, borderRadius: 4 }
            ]
        },
        options: {
            responsive: true, maintainAspectRatio: true,
            onClick: (e, elements) => {
                if (elements.length > 0) {
                    const idx = elements[0].datasetIndex === undefined ? elements[0].index : elements[0].index;
                    const month = _monthLabels[idx];
                    if (month) setFilter('month', month);
                }
            },
            interaction: { intersect: false, mode: 'index' },
            plugins: {
                legend: { position: 'top', labels: { font: { size: 12 } } },
                tooltip: { callbacks: { label: (ctx) => `${ctx.dataset.label}: ¥${fmt(ctx.parsed)}` } }
            },
            scales: {
                x: { grid: { display: false }, ticks: { font: { size: 10 } } },
                y: { beginAtZero: true, ticks: { font: { size: 11 }, callback: (v) => '¥' + (v >= 10000 ? (v/10000).toFixed(1) + '万' : v) } }
            }
        }
    });
}

// ========== 灵活筛选 ==========

/** 当前活跃的筛选条件 */
const filters = {
    category: '',
    month: '',
    io: '',
    amountMin: '',
    amountMax: '',
    keyword: '',
};

function setFilter(key, value) {
    filters[key] = value;
    // 同步到界面控件
    if (key === 'category') {
        const sel = document.getElementById('filterCategory');
        // 看有没有这个选项
        let found = false;
        for (let i = 0; i < sel.options.length; i++) {
            if (sel.options[i].value === value) {
                sel.selectedIndex = i;
                found = true;
                break;
            }
        }
        if (!found) {
            // 动态加一个
            const opt = document.createElement('option');
            opt.value = value;
            opt.text = value;
            sel.add(opt);
            sel.value = value;
        }
    } else if (key === 'month') {
        document.getElementById('filterMonth').value = value;
    } else if (key === 'io') {
        document.getElementById('filterIO').value = value;
    } else if (key === 'amountMin') {
        document.getElementById('filterAmountMin').value = value;
    } else if (key === 'amountMax') {
        document.getElementById('filterAmountMax').value = value;
    } else if (key === 'keyword') {
        document.getElementById('filterKeyword').value = value;
    }
    loadTransactions();
}

function applyFilters() {
    filters.category = document.getElementById('filterCategory').value;
    filters.month = document.getElementById('filterMonth').value;
    filters.io = document.getElementById('filterIO').value;
    filters.amountMin = document.getElementById('filterAmountMin').value;
    filters.amountMax = document.getElementById('filterAmountMax').value;
    filters.keyword = document.getElementById('filterKeyword')?.value || '';
    loadTransactions();
}

function clearFilters() {
    filters.category = '';
    filters.month = '';
    filters.io = '';
    filters.amountMin = '';
    filters.amountMax = '';
    filters.keyword = '';
    document.getElementById('filterCategory').value = '';
    document.getElementById('filterMonth').value = '';
    document.getElementById('filterIO').value = '';
    document.getElementById('filterAmountMin').value = '';
    document.getElementById('filterAmountMax').value = '';
    if (document.getElementById('filterKeyword')) document.getElementById('filterKeyword').value = '';
    loadTransactions();
}

function filterByPeer(peer) {
    filters.keyword = peer;
    if (document.getElementById('filterKeyword')) document.getElementById('filterKeyword').value = peer;
    loadTransactions();
}

async function loadTransactions() {
    const el = document.getElementById('txList');
    const countEl = document.getElementById('txCount');
    el.innerHTML = '<p class="tx-loading">加载中...</p>';
    countEl.textContent = '';

    try {
        // 从API获取所有数据，前端做过滤（更灵活）
        const cat = filters.category;
        const month = filters.month;
        const io = filters.io;
        let url = API_BASE + '/api/transactions?limit=2000';
        if (cat) url += '&category=' + encodeURIComponent(cat);
        if (month) url += '&month=' + encodeURIComponent(month);
        if (io) url += '&io=' + encodeURIComponent(io);
        const res = await fetch(url, { headers: { 'Authorization': 'Bearer ' + token } });
        if (!res.ok) return;
        const data = await res.json();

        let tx = data.transactions || [];

        // 前端金额筛选
        const minVal = parseFloat(filters.amountMin);
        const maxVal = parseFloat(filters.amountMax);
        if (!isNaN(minVal)) tx = tx.filter(t => t.amount >= minVal);
        if (!isNaN(maxVal)) tx = tx.filter(t => t.amount <= maxVal);

        // 前端关键词筛选（模糊搜索对方/商品/类型）
        const kw = (filters.keyword || '').trim();
        if (kw) {
            const kwl = kw.toLowerCase();
            tx = tx.filter(t =>
                (t.peer && t.peer.toLowerCase().includes(kwl)) ||
                (t.goods && t.goods.toLowerCase().includes(kwl)) ||
                (t.type && t.type.toLowerCase().includes(kwl)) ||
                (t.category && t.category.toLowerCase().includes(kwl))
            );
        }

        allTransactions = tx;

        if (tx.length === 0) {
            countEl.textContent = '没有匹配的记录';
            el.innerHTML = '<p class="tx-empty">没有匹配的交易记录</p>';
            return;
        }

        countEl.innerHTML = `共 <strong>${tx.length}</strong> 条记录`;
        if (tx.length > 200) {
            countEl.innerHTML += `（显示前200条）`;
        }

        el.innerHTML = tx.slice(0, 200).map(t => {
            const catBadge = t.category !== '其他' ? `<span class="tx-category" onclick="setFilter('category','${esc(t.category)}')">${esc(t.category)}</span>` : '';
            return `
            <div class="tx-item">
                <div class="tx-left">
                    <div class="tx-peer">
                        <a href="javascript:void(0)" onclick="filterByPeer('${esc(t.peer)}')">${esc(t.peer || '(无)')}</a>
                    </div>
                    <div class="tx-meta">
                        ${t.time ? t.time.slice(0, 10) : ''}
                        &nbsp; ${esc(t.type)}
                        ${catBadge}
                    </div>
                </div>
                <div class="tx-right">
                    <span class="${t.io === '收入' ? 'tx-income' : 'tx-expense'}">
                        ${t.io === '收入' ? '+' : '-'}¥${fmt(t.amount)}
                    </span>
                </div>
            </div>`;
        }).join('');
    } catch(e) { console.error(e); }
}

// ========== 工具 ==========
function fmt(v) {
    if (v === undefined || v === null) return '0.00';
    return Number(v).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function esc(s) {
    if (!s) return '';
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
}

// 默认进入时加载全部明细
window.addEventListener('load', () => {
    if (token) {
        setTimeout(loadTransactions, 500);
    }
});
