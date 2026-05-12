# ComfyUI API Gateway

统一 API 网关，将多个 ComfyUI 后端的 workflow 封装为简洁的 REST API 端点，并附带 Web 管理面板。

## 功能

- **动态路由** — 基于 YAML 配置，自动将 ComfyUI workflow 注册为 `POST /workflow-name` 端点
- **参数注入** — 自动将 API 请求参数注入 workflow JSON 模板（文本、图片、数值、seed）
- **多后端管理** — 支持多个 ComfyUI 服务器，不同 workflow 路由到不同后端，自动健康检查
- **Web 管理面板** — 可视化管理工作流配置、服务器状态、调用统计
- **AI 审核** — 上传 workflow JSON，自动分析节点并推荐 config 配置
- **任务追踪** — `task_id` → 实时状态 → 结果输出，标准 API 响应
- **统计报表** — SQLite 记录每次调用，成功率、耗时、错误日志
- **无外部依赖** — 无需数据库服务，无需消息队列，一键启动

## 架构

```
客户端 → POST /z-image {text, width, height}
              │
              ▼
     ┌─────────────────┐
     │  ComfyUI API    │
     │  Gateway:8288   │
     │                 │
     │ 1.加载 config    │
     │ 2.选择后端服务器  │
     │ 3.注入参数到     │
     │   workflow JSON │
     │ 4.提交到 ComfyUI │
     │ 5.监听进度       │
     │ 6.返回结果       │
     └────┬───┬────────┘
          │   │
    ┌─────┘   └─────┐
    ▼               ▼
┌────────┐    ┌────────┐
│ComfyUI │    │ComfyUI │
│:8188   │    │:8189   │
└────────┘    └────────┘
```

## 快速开始

### 环境要求

- Python 3.10+
- 至少一个已运行的 [ComfyUI](https://github.com/comfyanonymous/ComfyUI) 实例

### 安装

```bash
# 克隆项目
git clone https://github.com/nosee818/comfyui-api.git
cd comfyui-api

# 安装依赖
pip install -r requirements.txt
```

### 配置

#### 1. 配置后端服务器

编辑 `configs/servers.yaml`：

```yaml
servers:
  - id: "server-1"
    name: "主服务器"
    host: "10.192.6.192"
    port: 8188
    enabled: true

  - id: "server-2"
    name: "副服务器"
    host: "10.192.6.192"
    port: 8189
    enabled: true
```

#### 2. 添加 ComfyUI workflow

将 ComfyUI 导出的 workflow JSON（API Format）放入 `configs/workflows_json/`，例如 `my-workflow.json`。

在 `configs/workflows/` 创建对应的 YAML 配置文件，例如 `my-workflow.yaml`：

```yaml
name: "我的文生图"
route: "/my-workflow"
method: POST
description: "自定义文生图流程"
workflow_file: "my-workflow.json"
timeout: 120
backend_servers:
  - "server-1"

inputs:
  - name: text
    type: string
    required: true
    description: "图片描述"
    inject_to:
      node_id: "6"
      field: "text"

  - name: width
    type: integer
    required: false
    default: 1080
    inject_to:
      node_id: "5"
      field: "width"

  - name: height
    type: integer
    required: false
    default: 1920
    inject_to:
      node_id: "5"
      field: "height"

output_node_id: "9"
```

#### 3. 设置 workflow JSON 模板占位符

在 workflow JSON 中，将需要动态注入的值替换为 `{{参数名}}`：

```json
{
  "6": {
    "class_type": "CLIPTextEncode",
    "inputs": {
      "text": "{{text}}",
      "clip": ["4", 1]
    }
  }
}
```

### 启动

```bash
# 默认端口 8288
python run.py

# 自定义端口
python run.py --port 9000

# 自定义端口和地址
python run.py --port 9000 --host 0.0.0.0
```

也可以通过环境变量配置：

```bash
export CGW_GATEWAY_PORT=9000
python run.py
```

启动后访问：
- 管理面板：`http://localhost:8288/admin/`
- API 文档：`http://localhost:8288/docs`

## 管理面板

通过 Web UI 管理所有配置，无需手动编辑文件：

| 页面 | 功能 |
|------|------|
| **概览** | 系统状态总览、快速导航 |
| **工作流** | 查看/删除已注册的 API 端点 |
| **新建工作流** | 上传 workflow JSON → AI 自动分析节点 → 确认参数 → 保存 |
| **服务器** | 查看后端 ComfyUI 服务器在线状态，手动触发健康检查 |
| **统计** | 每个 API 的调用次数、成功率、平均耗时、最近任务列表 |

## API 参考

### Workflow 接口

由 config 动态生成，以 `/z-image` 为例：

```bash
POST /z-image
Content-Type: multipart/form-data

text=一只可爱的猫
width=1080
height=1920
seed=-1

# 响应
{
  "task_id": "uuid-xxxx",
  "status": "pending",
  "message": "Task submitted",
  "created_at": "2026-05-12T10:00:00Z"
}
```

### 任务查询

```bash
GET /task/{task_id}

# 响应
{
  "task_id": "uuid-xxxx",
  "status": "completed",
  "progress": 100,
  "outputs": [
    {
      "filename": "z-image_00001.png",
      "url": "http://10.192.6.192:8188/view?filename=z-image_00001.png&type=output"
    }
  ]
}
```

### 管理 API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/admin/api/reload` | 热重载所有 config |
| GET | `/admin/api/configs` | 列出所有 config |
| POST | `/admin/api/configs` | 创建 config |
| POST | `/admin/api/configs/analyze` | AI 分析 workflow JSON |
| DELETE | `/admin/api/configs/{route}` | 删除 config |
| GET | `/admin/api/servers` | 服务器状态列表 |
| POST | `/admin/api/servers/check` | 触发健康检查 |
| GET | `/admin/api/stats` | 统计报表 |
| GET | `/admin/api/tasks/recent` | 最近任务 |

### 健康检查

```bash
GET /health
# {"status": "ok", "service": "comfyui-api-gateway", "version": "0.1.0"}
```

## 支持的工作流类型

| 类型 | 说明 | config `type` |
|------|------|---------------|
| 文生图 | 文本描述 → 图片 | `string` + `integer` |
| 图生图 | 文本 + 1~N 张参考图 → 图片 | `string` + `image_sequence` |
| 视频生成 | 文本/图片 → 视频 | 同上 + output_node_id 指向 VHS_VideoCombine 等 |
| 任意 workflow | 任何 ComfyUI workflow 都可封装 | 自动分析 |

## 项目结构

```
comfyui-api/
├── app/
│   ├── main.py                 # FastAPI 入口
│   ├── config.py               # 全局配置（支持环境变量 CGW_*）
│   ├── models/
│   │   ├── workflow.py         # WorkflowConfig, WorkflowInput
│   │   └── task.py             # TaskResponse, TaskStatusResponse
│   ├── core/
│   │   ├── gateway.py          # API 网关核心
│   │   ├── injector.py         # 参数注入器
│   │   ├── comfyui_client.py   # ComfyUI HTTP/WS 客户端
│   │   └── router.py           # 动态路由注册
│   ├── manager/
│   │   ├── server_manager.py   # 后端服务器管理 + 健康检查
│   │   ├── config_manager.py   # Config CRUD + AI 分析
│   │   └── stats.py            # SQLite 统计
│   ├── web/
│   │   ├── admin.py            # 管理面板路由
│   │   └── templates/          # Jinja2 页面
│   └── utils/                  # 日志、工具
├── configs/
│   ├── servers.yaml            # 后端服务器列表
│   ├── workflows/              # workflow config YAML
│   └── workflows_json/         # ComfyUI workflow JSON 模板
├── run.py                      # 启动脚本
└── requirements.txt
```

## 环境变量

所有 `app/config.py` 中的配置项都可通过 `CGW_` 前缀环境变量覆盖：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CGW_GATEWAY_HOST` | `0.0.0.0` | 绑定地址 |
| `CGW_GATEWAY_PORT` | `8288` | 服务端口 |
| `CGW_LOG_LEVEL` | `INFO` | 日志级别 |
| `CGW_HEALTH_CHECK_INTERVAL` | `30` | 健康检查间隔（秒） |

## systemd 部署

创建 `/etc/systemd/system/comfyui-gateway.service`：

```ini
[Unit]
Description=ComfyUI API Gateway
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/data/comfyui_api
ExecStart=/usr/bin/python3 run.py --port 8288
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable comfyui-gateway
systemctl start comfyui-gateway
```

## License

MIT
