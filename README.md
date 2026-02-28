# TicketSystem Sync API

一个轻量级 Python API 服务：把你自己的 App 操作直接同步到 Fusion 工单表（Datasheet），避免手动维护表格。

## 功能

- `GET /api/tickets`：读取工单列表
- `POST /api/tickets`：新增工单
- `PATCH /api/tickets/:recordId`：更新工单
- `DELETE /api/tickets/:recordId`：删除工单
- `GET /health`：健康检查

所有接口会实时调用 Fusion OpenAPI，因此工单系统表就是唯一数据源。

## 快速开始

1. 准备环境变量

```bash
cp .env.example .env
```

然后编辑 `.env`，填入你的 token。

2. 启动

```bash
export $(cat .env | xargs)
python3 app.py
```

默认地址：`http://localhost:8080`

## 请求示例

### 查询工单

```bash
curl "http://localhost:8080/api/tickets"
```

### 新增工单

```bash
curl -X POST "http://localhost:8080/api/tickets" \
  -H "Content-Type: application/json" \
  -d '{
    "fields": {
      "标题": "登录报错",
      "优先级": "高",
      "状态": "待处理"
    }
  }'
```

### 更新工单

```bash
curl -X PATCH "http://localhost:8080/api/tickets/recxxxxxxxx" \
  -H "Content-Type: application/json" \
  -d '{
    "fields": {
      "状态": "处理中"
    }
  }'
```

### 删除工单

```bash
curl -X DELETE "http://localhost:8080/api/tickets/recxxxxxxxx"
```

## 建议接入方式

你可以把这个服务当作“中间层 API”：

- 前端 App / 小程序 / 管理后台只访问本服务；
- 本服务再访问 Fusion 表；
- 后续若要加权限、字段映射、流程控制，只改本服务即可。

