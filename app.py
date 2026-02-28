#!/usr/bin/env python3
import json
import os
import re
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen


class FusionConfigError(RuntimeError):
    pass


class FusionClient:
    def __init__(self) -> None:
        self.base_url = os.getenv("FUSION_BASE_URL", "https://yach-vika.zhiyinlou.com/fusion/v1")
        self.token = os.getenv("FUSION_TOKEN")
        self.datasheet_id = os.getenv("FUSION_DATASHEET_ID", "dstjpwCCYCubQ53M9M")
        self.view_id = os.getenv("FUSION_VIEW_ID", "viw1vsFKMMcvp")
        self.field_key = os.getenv("FUSION_FIELD_KEY", "name")

        if not self.token:
            raise FusionConfigError("Missing FUSION_TOKEN. Please set it in your environment.")

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, str]] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        url = f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"
        if params:
            url = f"{url}?{urlencode(params)}"

        data = None
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")

        req = Request(url=url, method=method, headers=headers, data=data)
        try:
            with urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8") or "{}"
                return json.loads(raw)
        except HTTPError as err:
            body = err.read().decode("utf-8", errors="ignore")
            try:
                parsed = json.loads(body) if body else {}
            except json.JSONDecodeError:
                parsed = {"message": body}
            return {"success": False, "status": err.code, "error": parsed}
        except URLError as err:
            return {"success": False, "status": 502, "error": {"message": str(err)}}
        except Exception as err:  # noqa: BLE001
            return {"success": False, "status": 500, "error": {"message": str(err)}}

    def list_records(self) -> Dict[str, Any]:
        return self._request(
            "GET",
            f"datasheets/{self.datasheet_id}/records",
            params={
                "viewId": self.view_id,
                "fieldKey": self.field_key,
            },
        )

    def create_record(self, fields: Dict[str, Any]) -> Dict[str, Any]:
        return self._request(
            "POST",
            f"datasheets/{self.datasheet_id}/records",
            params={"fieldKey": self.field_key},
            payload={"records": [{"fields": fields}]},
        )

    def update_record(self, record_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
        return self._request(
            "PATCH",
            f"datasheets/{self.datasheet_id}/records",
            params={"fieldKey": self.field_key},
            payload={"records": [{"recordId": record_id, "fields": fields}]},
        )

    def delete_record(self, record_id: str) -> Dict[str, Any]:
        return self._request(
            "DELETE",
            f"datasheets/{self.datasheet_id}/records",
            params={"recordIds": record_id},
        )


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(_safe_text(item) for item in value)
    if isinstance(value, dict):
        return " ".join(_safe_text(v) for v in value.values())
    return str(value).strip()


def _extract_records(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    data = payload.get("data")
    if isinstance(data, dict):
        records = data.get("records")
        if isinstance(records, list):
            return records
    records = payload.get("records")
    return records if isinstance(records, list) else []


def _get_field(fields: Dict[str, Any], candidates: List[str]) -> str:
    lowered = {str(k).lower(): v for k, v in fields.items()}
    for candidate in candidates:
        if candidate in fields:
            return _safe_text(fields.get(candidate))
        lc = candidate.lower()
        if lc in lowered:
            return _safe_text(lowered.get(lc))
    return ""


def _parse_date(raw: Any) -> Optional[datetime]:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        if raw > 10**12:
            return datetime.fromtimestamp(raw / 1000)
        return datetime.fromtimestamp(raw)

    text = _safe_text(raw)
    if not text:
        return None

    fmts = [
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
    ]
    for fmt in fmts:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _tokenize(text: str) -> set:
    pieces = re.findall(r"[\u4e00-\u9fff]|[a-zA-Z0-9]+", text.lower())
    return {piece for piece in pieces if piece}


def _similarity(a: str, b: str) -> float:
    ta = _tokenize(a)
    tb = _tokenize(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _summarize_issue(text: str) -> str:
    clean = re.sub(r"\s+", " ", text).strip()
    return clean[:40] + ("..." if len(clean) > 40 else "")


def analyze_top_issues(
    records: List[Dict[str, Any]],
    *,
    start_date: Optional[datetime],
    end_date: Optional[datetime],
    product_filter: str,
    min_count: int,
) -> Dict[str, Any]:
    date_keys = ["问题接收日期", "接收日期", "日期", "创建时间", "createdAt", "CreatedAt"]
    product_keys = ["产品线", "productLine", "产品", "业务线"]
    platform_keys = ["所属端", "端", "平台", "app端"]
    link_keys = ["工单链接", "链接", "ticketLink", "url"]
    desc_keys = ["问题描述", "描述", "summary", "标题"]
    progress_keys = ["处理进展", "进展", "处理状态"]
    conclusion_keys = ["问题结论", "结论", "原因"]

    normalized: List[Dict[str, Any]] = []
    for record in records:
        fields = record.get("fields") if isinstance(record.get("fields"), dict) else {}
        received_date_raw = _get_field(fields, date_keys)
        received_date = _parse_date(received_date_raw)
        product_line = _get_field(fields, product_keys)
        platform = _get_field(fields, platform_keys)
        issue_text = " | ".join(
            part for part in [
                _get_field(fields, desc_keys),
                _get_field(fields, progress_keys),
                _get_field(fields, conclusion_keys),
            ] if part
        )
        if not issue_text:
            issue_text = json.dumps(fields, ensure_ascii=False)

        ticket_link = _get_field(fields, link_keys)
        if not ticket_link:
            ticket_link = f"record:{record.get('recordId', '')}"

        normalized.append(
            {
                "recordId": record.get("recordId", ""),
                "fields": fields,
                "receivedDate": received_date,
                "receivedDateRaw": received_date_raw,
                "productLine": product_line,
                "platform": platform or "未知",
                "ticketLink": ticket_link,
                "issueText": issue_text,
            }
        )

    product_filter_lc = product_filter.lower().strip()
    filtered = []
    for ticket in normalized:
        ticket_date = ticket["receivedDate"]
        if start_date and (not ticket_date or ticket_date.date() < start_date.date()):
            continue
        if end_date and (not ticket_date or ticket_date.date() > end_date.date()):
            continue
        if product_filter_lc and product_filter_lc not in ticket["productLine"].lower():
            continue
        filtered.append(ticket)

    total = len(filtered)
    clusters: List[Dict[str, Any]] = []
    for ticket in filtered:
        matched = None
        for cluster in clusters:
            if _similarity(ticket["issueText"], cluster["referenceText"]) >= 0.45:
                matched = cluster
                break

        if not matched:
            matched = {
                "referenceText": ticket["issueText"],
                "tickets": [],
                "platformCounter": {},
            }
            clusters.append(matched)

        matched["tickets"].append(ticket)
        platform = ticket["platform"]
        matched["platformCounter"][platform] = matched["platformCounter"].get(platform, 0) + 1

    top_issues = []
    for cluster in clusters:
        count = len(cluster["tickets"])
        if count < min_count:
            continue
        sample = cluster["tickets"][0]
        ratio = (count / total * 100) if total else 0
        top_issues.append(
            {
                "summary": _summarize_issue(sample["issueText"]),
                "count": count,
                "platform": ", ".join(
                    f"{k}({v})" for k, v in sorted(cluster["platformCounter"].items(), key=lambda item: item[1], reverse=True)
                ),
                "ratioInFiltered": round(ratio, 2),
                "ticketLinks": [ticket["ticketLink"] for ticket in cluster["tickets"]],
                "recordIds": [ticket["recordId"] for ticket in cluster["tickets"]],
            }
        )

    top_issues.sort(key=lambda item: item["count"], reverse=True)

    return {
        "filters": {
            "startDate": start_date.strftime("%Y-%m-%d") if start_date else None,
            "endDate": end_date.strftime("%Y-%m-%d") if end_date else None,
            "productLine": product_filter,
            "minCount": min_count,
        },
        "totalTicketsInScope": total,
        "topIssues": top_issues,
        "pieChart": {
            "labels": [item["summary"] for item in top_issues],
            "values": [item["count"] for item in top_issues],
        },
    }


DASHBOARD_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>线上工单分析台</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <style>
    body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;margin:0;background:#f6f8fb;color:#222}
    .container{max-width:1280px;margin:24px auto;padding:0 16px}
    .card{background:#fff;border-radius:12px;padding:16px;margin-bottom:16px;box-shadow:0 2px 10px rgba(0,0,0,.05)}
    h1,h2,h3{margin:0 0 12px 0}
    .row{display:flex;gap:12px;flex-wrap:wrap;align-items:end}
    .grid{display:grid;grid-template-columns:2fr 1fr;gap:16px}
    .grid-form{display:grid;grid-template-columns:repeat(3,minmax(220px,1fr));gap:10px}
    @media (max-width:1000px){.grid,.grid-form{grid-template-columns:1fr}}
    label{display:flex;flex-direction:column;font-size:13px;gap:6px}
    input,textarea,button,select{font:inherit}
    input,textarea,select{padding:8px;border:1px solid #ddd;border-radius:8px}
    textarea{min-height:80px}
    button{padding:8px 12px;border:none;border-radius:8px;background:#2563eb;color:white;cursor:pointer}
    button.secondary{background:#475569}
    button.danger{background:#dc2626}
    table{width:100%;border-collapse:collapse;font-size:13px}
    th,td{border-bottom:1px solid #edf2f7;padding:8px;text-align:left;vertical-align:top}
    .muted{color:#64748b}
    .actions{display:flex;gap:8px;flex-wrap:wrap}
    .pill{padding:2px 8px;border-radius:999px;background:#e2e8f0;color:#334155;font-size:12px}
  </style>
</head>
<body>
  <div class="container">
    <h1>线上用户反馈工单系统（App 同步版）</h1>

    <div class="card">
      <h2>每周 Top 问题分析</h2>
      <div class="row">
        <label>开始日期<input id="startDate" type="date" /></label>
        <label>结束日期<input id="endDate" type="date" /></label>
        <label>产品线关键字<input id="productLine" value="online" placeholder="如 online / 大小班" /></label>
        <label>最小工单数<input id="minCount" type="number" value="2" min="1" /></label>
        <button onclick="loadTopIssues()">查询 Top 问题</button>
      </div>
      <p class="muted" id="scopeText"></p>
      <div class="grid">
        <div>
          <table>
            <thead><tr><th>简洁问题描述</th><th>工单数</th><th>所属端</th><th>占比(筛选范围)</th><th>工单链接</th></tr></thead>
            <tbody id="topIssuesBody"></tbody>
          </table>
        </div>
        <div><canvas id="issuesPie"></canvas></div>
      </div>
    </div>

    <div class="card">
      <h2>工单维护（更友好录入）</h2>
      <p class="muted">不需要再手动填写 JSON 或 recordId。先填表单，点击保存即可；如需修改，点下方工单行的“编辑”。</p>
      <div class="grid-form">
        <label>问题接收日期<input id="fDate" type="date" /></label>
        <label>产品线
          <select id="fProductLine">
            <option value="online课">online课</option>
            <option value="大小班">大小班</option>
            <option value="其它">其它</option>
          </select>
        </label>
        <label>所属端
          <select id="fPlatform">
            <option value="学生端">学生端</option>
            <option value="老师端">老师端</option>
            <option value="管理后台">管理后台</option>
            <option value="其它">其它</option>
          </select>
        </label>
        <label>优先级
          <select id="fPriority">
            <option value="高">高</option>
            <option value="中" selected>中</option>
            <option value="低">低</option>
          </select>
        </label>
        <label>状态
          <select id="fStatus">
            <option value="待处理">待处理</option>
            <option value="处理中">处理中</option>
            <option value="已解决">已解决</option>
            <option value="已关闭">已关闭</option>
          </select>
        </label>
        <label>工单链接<input id="fLink" placeholder="https://..." /></label>
      </div>
      <div style="margin-top:10px">
        <label>问题描述<textarea id="fDescription" placeholder="请简要描述用户反馈的问题现象"></textarea></label>
      </div>
      <div style="margin-top:10px">
        <label>处理进展<textarea id="fProgress" placeholder="当前排查过程 / 已做动作"></textarea></label>
      </div>
      <div style="margin-top:10px">
        <label>问题结论<textarea id="fConclusion" placeholder="根因 / 结论（可暂空）"></textarea></label>
      </div>
      <div class="row" style="margin-top:12px">
        <span class="pill" id="editState">当前：新增模式</span>
        <button onclick="saveTicket()">保存工单</button>
        <button onclick="resetForm()" class="secondary">清空表单</button>
        <button onclick="loadTickets()" class="secondary">刷新工单列表</button>
      </div>
    </div>

    <div class="card">
      <h2>工单列表</h2>
      <table>
        <thead><tr><th>日期</th><th>产品线</th><th>描述</th><th>所属端</th><th>状态</th><th>操作</th></tr></thead>
        <tbody id="ticketsBody"></tbody>
      </table>
    </div>
  </div>

<script>
let pieChart;
let ticketsCache = [];
let editingRecordId = null;

function todayOffset(days){
  const d = new Date();
  d.setDate(d.getDate()+days);
  return d.toISOString().slice(0,10);
}

async function api(path, options={}) {
  const res = await fetch(path, {headers:{'Content-Type':'application/json'}, ...options});
  const data = await res.json();
  if (!res.ok) throw new Error(data.message || JSON.stringify(data));
  if (data && data.success === false && data.error) throw new Error(data.error.message || JSON.stringify(data.error));
  return data;
}

function safe(v){ return (v ?? '').toString(); }

function collectFormFields(){
  return {
    '问题接收日期': document.getElementById('fDate').value,
    '产品线': document.getElementById('fProductLine').value,
    '所属端': document.getElementById('fPlatform').value,
    '优先级': document.getElementById('fPriority').value,
    '状态': document.getElementById('fStatus').value,
    '工单链接': document.getElementById('fLink').value.trim(),
    '问题描述': document.getElementById('fDescription').value.trim(),
    '处理进展': document.getElementById('fProgress').value.trim(),
    '问题结论': document.getElementById('fConclusion').value.trim(),
  };
}

function fillForm(ticket){
  document.getElementById('fDate').value = safe(ticket.receivedDateRaw).slice(0,10);
  document.getElementById('fProductLine').value = safe(ticket.productLine || '其它');
  document.getElementById('fPlatform').value = safe(ticket.platform || '其它');
  document.getElementById('fPriority').value = safe(ticket.priority || '中');
  document.getElementById('fStatus').value = safe(ticket.status || '待处理');
  document.getElementById('fLink').value = safe(ticket.ticketLink);
  document.getElementById('fDescription').value = safe(ticket.description);
  document.getElementById('fProgress').value = safe(ticket.progress);
  document.getElementById('fConclusion').value = safe(ticket.conclusion);
}

function resetForm(){
  editingRecordId = null;
  document.getElementById('editState').textContent = '当前：新增模式';
  document.getElementById('fDate').value = todayOffset(0);
  document.getElementById('fProductLine').value = 'online课';
  document.getElementById('fPlatform').value = '学生端';
  document.getElementById('fPriority').value = '中';
  document.getElementById('fStatus').value = '待处理';
  document.getElementById('fLink').value = '';
  document.getElementById('fDescription').value = '';
  document.getElementById('fProgress').value = '';
  document.getElementById('fConclusion').value = '';
}

async function saveTicket(){
  const fields = collectFormFields();
  if (!fields['问题描述']) {
    alert('请先填写问题描述');
    return;
  }

  if (editingRecordId) {
    await api('/api/tickets/'+editingRecordId, {method:'PATCH', body: JSON.stringify({fields})});
  } else {
    await api('/api/tickets', {method:'POST', body: JSON.stringify({fields})});
  }

  await Promise.all([loadTickets(), loadTopIssues()]);
  resetForm();
}

function onEdit(recordId){
  const ticket = ticketsCache.find(t => t.recordId === recordId);
  if (!ticket) return;
  editingRecordId = recordId;
  document.getElementById('editState').textContent = '当前：编辑模式（已选中1条工单）';
  fillForm(ticket);
  window.scrollTo({top: document.body.scrollHeight * 0.25, behavior: 'smooth'});
}

async function onDelete(recordId){
  if (!confirm('确认删除这条工单？')) return;
  await api('/api/tickets/'+recordId, {method:'DELETE'});
  await Promise.all([loadTickets(), loadTopIssues()]);
  if (editingRecordId === recordId) resetForm();
}

async function loadTopIssues(){
  const startDate = document.getElementById('startDate').value;
  const endDate = document.getElementById('endDate').value;
  const productLine = document.getElementById('productLine').value;
  const minCount = document.getElementById('minCount').value || 2;
  const params = new URLSearchParams({startDate,endDate,productLine,minCount});
  const data = await api('/api/analytics/top-issues?'+params.toString());

  document.getElementById('scopeText').textContent = `筛选范围工单总数: ${data.totalTicketsInScope}`;

  const tbody = document.getElementById('topIssuesBody');
  tbody.innerHTML = '';
  data.topIssues.forEach(item => {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${item.summary}</td><td>${item.count}</td><td>${item.platform}</td><td>${item.ratioInFiltered}%</td><td>${item.ticketLinks.map(link=>`<div>${link}</div>`).join('')}</td>`;
    tbody.appendChild(tr);
  });

  const ctx = document.getElementById('issuesPie');
  if (pieChart) pieChart.destroy();
  pieChart = new Chart(ctx, {
    type: 'pie',
    data: {
      labels: data.pieChart.labels,
      datasets: [{ data: data.pieChart.values }]
    }
  });
}

async function loadTickets(){
  const payload = await api('/api/tickets/normalized');
  ticketsCache = payload.records || [];
  const tbody = document.getElementById('ticketsBody');
  tbody.innerHTML = '';
  ticketsCache.slice(0,300).forEach(t => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${safe(t.receivedDateRaw).slice(0,10)}</td>
      <td>${safe(t.productLine)}</td>
      <td>${safe(t.description)}</td>
      <td>${safe(t.platform)}</td>
      <td>${safe(t.status)}</td>
      <td>
        <div class="actions">
          <button class="secondary" onclick="onEdit('${safe(t.recordId)}')">编辑</button>
          <button class="danger" onclick="onDelete('${safe(t.recordId)}')">删除</button>
        </div>
      </td>`;
    tbody.appendChild(tr);
  });
}

window.addEventListener('load', async () => {
  document.getElementById('startDate').value = todayOffset(-7);
  document.getElementById('endDate').value = todayOffset(0);
  resetForm();
  try {
    await Promise.all([loadTopIssues(), loadTickets()]);
  } catch (e) {
    alert('加载失败: '+e.message);
  }
});
</script>
</body>
</html>
"""


class TicketAPIHandler(BaseHTTPRequestHandler):
    client: FusionClient

    def _send(self, code: int, payload: Dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_html(self, html: str) -> None:
        data = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _parse_json(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length > 0 else b"{}"
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send_html(DASHBOARD_HTML)
            return
        if parsed.path == "/health":
            self._send(200, {"ok": True})
            return
        if parsed.path == "/api/tickets":
            self._send(200, self.client.list_records())
            return
        if parsed.path == "/api/tickets/normalized":
            raw_payload = self.client.list_records()
            records = _extract_records(raw_payload)
            out = []
            for record in records:
                fields = record.get("fields") if isinstance(record.get("fields"), dict) else {}
                out.append(
                    {
                        "recordId": record.get("recordId", ""),
                        "productLine": _get_field(fields, ["产品线", "productLine", "产品", "业务线"]),
                        "receivedDateRaw": _get_field(fields, ["问题接收日期", "接收日期", "日期", "创建时间"]),
                        "description": _get_field(fields, ["问题描述", "描述", "summary", "标题"]),
                        "platform": _get_field(fields, ["所属端", "端", "平台", "app端"]),
                        "status": _get_field(fields, ["状态", "status"]),
                        "priority": _get_field(fields, ["优先级", "priority"]),
                        "progress": _get_field(fields, ["处理进展", "进展", "处理状态"]),
                        "conclusion": _get_field(fields, ["问题结论", "结论", "原因"]),
                        "ticketLink": _get_field(fields, ["工单链接", "链接", "ticketLink", "url"]),
                    }
                )
            self._send(200, {"records": out})
            return
        if parsed.path == "/api/analytics/top-issues":
            query = parse_qs(parsed.query)
            start_date = _parse_date(query.get("startDate", [""])[0])
            end_date = _parse_date(query.get("endDate", [""])[0])
            if end_date:
                end_date = end_date + timedelta(hours=23, minutes=59, seconds=59)
            product_line = query.get("productLine", ["online"])[0]
            min_count_text = query.get("minCount", ["2"])[0]
            try:
                min_count = max(int(min_count_text), 1)
            except ValueError:
                min_count = 2

            raw_payload = self.client.list_records()
            records = _extract_records(raw_payload)
            analysis = analyze_top_issues(
                records,
                start_date=start_date,
                end_date=end_date,
                product_filter=product_line,
                min_count=min_count,
            )
            self._send(200, analysis)
            return
        self._send(404, {"message": "Not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/api/tickets":
            self._send(404, {"message": "Not found"})
            return

        body = self._parse_json()
        fields = body.get("fields")
        if not isinstance(fields, dict):
            self._send(400, {"message": "Body must be: { \"fields\": { ... } }"})
            return

        self._send(200, self.client.create_record(fields))

    def do_PATCH(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/tickets/"):
            self._send(404, {"message": "Not found"})
            return

        record_id = parsed.path.rsplit("/", 1)[-1]
        body = self._parse_json()
        fields = body.get("fields")
        if not isinstance(fields, dict):
            self._send(400, {"message": "Body must be: { \"fields\": { ... } }"})
            return

        self._send(200, self.client.update_record(record_id, fields))

    def do_DELETE(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/tickets/"):
            self._send(404, {"message": "Not found"})
            return
        record_id = parsed.path.rsplit("/", 1)[-1]
        self._send(200, self.client.delete_record(record_id))


def run() -> None:
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8080"))
    client = FusionClient()

    TicketAPIHandler.client = client

    server = ThreadingHTTPServer((host, port), TicketAPIHandler)
    print(f"Ticket app running at http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run()
