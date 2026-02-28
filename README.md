# TicketSystem App（Fusion 工单同步 + Top 问题分析）

这是一个可直接运行的 Python Web App：

- **把 Fusion 表当数据库**（不再手动改表）
- 在页面里**新增/更新/删除工单**，自动同步到线上工单表
- 自动做每周 **Top 相似问题分析**（支持日期和产品线筛选）
- 展示问题工单占比与饼图

> Fusion 接口来自你提供的 curl：
> `GET /fusion/v1/datasheets/{datasheetId}/records?viewId=...&fieldKey=name`

---

## 1) 配置

创建环境变量：

```bash
cp .env.example .env
export $(cat .env | xargs)
```

核心配置：

- `FUSION_TOKEN`：访问 token（必填）
- `FUSION_BASE_URL`：默认 `https://yach-vika.zhiyinlou.com/fusion/v1`
- `FUSION_DATASHEET_ID`：默认 `dstjpwCCYCubQ53M9M`
- `FUSION_VIEW_ID`：默认 `viw1vsFKMMcvp`
- `FUSION_FIELD_KEY`：默认 `name`

---

## 2) 启动

```bash
python3 app.py
```

打开：`http://localhost:8080`

---

## 3) 页面功能

### 工单维护（同步 Fusion）

- 友好表单录入（不需要手写 JSON）
- 工单列表行内“编辑/删除”（不需要手动输入 recordId）
- 支持录入：问题接收日期、产品线、所属端、优先级、状态、问题描述、处理进展、问题结论
- 创建时自动新增工单，不需要手填工单链接
- 点击工单行可打开“工单详情”，并可一键跳转外部工单链接（如果该工单已有链接）
- 保存后自动同步到 Fusion

### 每周 Top 问题分析

可筛选：

- 问题接收日期（开始/结束）
- 产品线关键字（例如 `online`、`大小班`）
- 最小工单数阈值（默认 ≥2）

输出内容：

- 简洁问题描述
- 工单数
- 所属端
- 在筛选范围内占比
- 工单链接
- 饼图

相似问题识别逻辑基于：

- 问题描述
- 处理进展
- 问题结论

并用 Jaccard 文本相似度自动聚类。

---

## 4) API（可单独接入）

- `GET /health`：健康检查
- `GET /api/tickets`：读取 Fusion 原始工单
- `GET /api/tickets/normalized`：读取标准化后的工单关键字段
- `GET /api/tickets/:recordId`：读取单条工单详情（用于详情面板）
- `POST /api/tickets`：新增工单
- `PATCH /api/tickets/:recordId`：更新工单
- `DELETE /api/tickets/:recordId`：删除工单
- `GET /api/analytics/top-issues?startDate=2026-01-01&endDate=2026-01-07&productLine=online&minCount=2`

---

## 5) 说明

- 本项目是纯 Python 标准库实现（后端）+ 浏览器端 Chart.js（前端图表）。
- 若你后续要做权限体系、字段映射、自动派单等，可以继续在这个 App 上扩展。
