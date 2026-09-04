"""全局配置：LLM 网关三通道（mock / ollama / openai 兼容云 API）。

通过环境变量或本文件默认值切换，代码不用改：
  LLM_PROVIDER=mock     开箱即用的演示通道（无需任何模型）
  LLM_PROVIDER=ollama   本地 Ollama（安装后: ollama pull qwen3:4b）
  LLM_PROVIDER=openai   OpenAI 兼容云 API（DeepSeek / GLM / GPT 等）
"""
import os

# ---- LLM 通道 ----
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "mock")  # mock | ollama | openai

# Ollama 通道
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:4b")

# OpenAI 兼容云 API 通道
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")

# ---- 数据库 ----
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./taskflow.db")

# 请求超时（秒）：本地小模型拆解大项目可能较慢
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "180"))

# ---- 考勤 webhook ----
# 统一事件 API 的共享密钥（POST /api/webhooks/attendance 请求头 X-Webhook-Secret）
# 生产环境必须设置，否则该端点拒绝服务
ATTENDANCE_WEBHOOK_SECRET = os.getenv("ATTENDANCE_WEBHOOK_SECRET", "")

# 飞书事件订阅的 Verification Token（开放平台-事件订阅配置页获取）
FEISHU_VERIFICATION_TOKEN = os.getenv("FEISHU_VERIFICATION_TOKEN", "")
