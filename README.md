# TaskFlow AI —— AI 任务分配系统

以大模型为核心的团队任务管理系统：项目录入 → AI 拆解为天级任务 → 人工审核 → 打卡自动派发 → 提交交付物 → AI 评估 → 员工画像更新 → 影响下次派发难度。

## 核心特性

- **滚动拆解**：LLM 先规划里程碑，再逐阶段拆成天级任务；前序阶段消化完才拆下一阶段
- **行业包**：知识型 / 生产型 / 响应型三套预设（拆解提示、评分权重、派发容量），适配不同行业
- **打卡事件驱动**：上班打卡自动领取当日任务（技能×难度爬坡×依赖×容量）；下班打卡生成当日汇总
- **评估可解释**：AI 按验收标准逐条判定（✅/⚠️/❌）并给出依据；防作弊检测（敷衍/重复提交自动标记）
- **考勤系统对接**：webhook 接收飞书/钉钉打卡事件；提供统一事件 API，任何考勤系统都能对接
- **排班约束**：标准工作日 / 上二休二
- **角色分离**：管理员端（项目/审核/分配/评估/考勤）与员工端（我的任务/记录/画像）
- **LLM 可插拔**：本地 Ollama（数据不出内网）/ OpenAI 兼容云 API / 演示 mock，改配置即切换

## 快速开始（Docker，推荐）

前置：宿主机安装 [Ollama](https://ollama.com) 并拉取模型：

```bash
ollama pull qwen3:4b
```

启动：

```bash
cp .env.example .env
docker compose up -d
```

打开 http://localhost:8600

- 管理员：`admin / admin123`
- 员工：`张工 / 123456`（演示数据，员工默认密码 123456）

> 没装 Docker？用 `backend/start.ps1`（Windows）或参考下面"免安装包"。

## 快速开始（免安装包，Windows）

解压 zip 后双击 `启动.bat`，自动启动 Ollama（需已安装）和应用，并打开浏览器。

## LLM 配置

| 通道 | LLM_PROVIDER | 说明 |
|---|---|---|
| 本地模型 | `ollama` | 默认。企业数据不出内网 |
| 云 API | `openai` | 兼容 DeepSeek / GLM / GPT 等，配 `LLM_BASE_URL` + `LLM_API_KEY` |
| 演示 | `mock` | 无需模型，跑通流程用 |

## 考勤系统对接

系统通过 webhook 接收打卡事件，员工上班打卡即自动领取当日任务。

**前置**：管理端「员工画像 → 🔗 绑定考勤」里给每个员工填平台成员 ID（飞书 ou_xxx / 钉钉 userid / 企微 userid）。

| 对接方式 | 端点 | 说明 |
|---|---|---|
| 飞书事件订阅 | `POST /api/webhooks/feishu` | 开放平台订阅考勤打卡事件；需公网可达 |
| 钉钉事件回调 | `POST /api/webhooks/dingtalk` | HTTP 回调模式 |
| **统一事件 API** | `POST /api/webhooks/attendance` | 任何系统都能对接（含企微，可用脚本转发） |

统一事件 API 示例（需设置环境变量 `ATTENDANCE_WEBHOOK_SECRET`）：

```bash
curl -X POST https://your-host/api/webhooks/attendance \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Secret: <你的密钥>" \
  -d '{"source":"wecom","external_id":"zhang_san","type":"in"}'
```

> 企业微信回调需 AES 消息解密，暂未内置适配器；用上面的统一 API 由企业侧脚本转发即可（webhook 端点返回 `{"matched": true, "employee": "..."}`）。

## 典型使用流程

```
管理员：录入项目（选行业包）→ AI 拆解 → 审核任务 → 员工打卡自动派发（或手动分配）
员工：  上班打卡 → 自动领取任务 → 干活 → 提交交付物 → 下班打卡 → 看评分反馈
管理员：触发 AI 评估 → 员工能力画像更新 → 影响明日任务难度
```

## 目录结构

```
backend/
├── app/
│   ├── industry/    行业包（知识型/生产型/响应型）
│   ├── llm/          LLM 网关（三通道）+ prompt
│   ├── services/     拆解/评估/派发/排班引擎
│   └── api/          REST 路由（public/admin/me + 考勤）
├── static/           Web 前端（无构建步骤）
├── Dockerfile
└── start.ps1         Windows 一键启动
docker-compose.yml
```

## 数据持久化

- Docker：命名卷 `taskflow-data`（SQLite + 密钥文件在容器 `/app/data`）
- 免安装：`backend/` 目录下的 `taskflow.db`

## 技术栈

Python 3.12 / FastAPI / SQLAlchemy / SQLite / 原生 JS 前端 / Ollama 或任意 OpenAI 兼容 API
