# TaskFlow AI —— AI 任务分配系统

以大模型为核心的团队任务管理系统：项目录入 → AI 拆解为天级任务 → 人工审核 → 打卡自动派发 → 提交交付物 → AI 评估 → 员工画像更新 → 影响下次派发难度。

## 核心特性

- **滚动拆解**：LLM 先规划里程碑，再逐阶段拆成天级任务；前序阶段消化完才拆下一阶段
- **行业包**：知识型 / 生产型 / 响应型三套预设（拆解提示、评分权重、派发容量），适配不同行业
- **打卡事件驱动**：上班打卡自动领取当日任务（技能×难度爬坡×依赖×容量）；下班打卡生成当日汇总
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
