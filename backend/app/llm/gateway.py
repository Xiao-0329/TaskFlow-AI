"""LLM 网关：统一 chat 接口，三通道可切换。

  mock    —— 无需任何模型，开箱即用（演示/开发）
  ollama  —— 本地 Ollama（隐私数据不出机器）
  openai  —— OpenAI 兼容云 API（DeepSeek/GLM/GPT 等，配 .env 即用）

所有通道统一返回纯文本；JSON 解析由调用方负责（见 parse_json）。
"""
import json
import re

import httpx

from .. import config


class LLMError(Exception):
    pass


def chat(system: str, user: str, schema: dict | None = None) -> str:
    """统一对话入口，返回模型文本。

    schema: 期望输出的 JSON Schema。ollama 通道用语法约束解码（format），
    物理上保证输出是合法 JSON 且思考文本不会混入；其他通道作为提示约束。
    """
    provider = config.LLM_PROVIDER
    if provider == "mock":
        return _mock_chat(system, user)
    if provider == "ollama":
        return _ollama_chat(system, user, schema)
    if provider == "openai":
        return _openai_chat(system, user)
    raise LLMError(f"未知 LLM_PROVIDER: {provider}（可选 mock / ollama / openai）")


def provider_info() -> dict:
    return {
        "provider": config.LLM_PROVIDER,
        "model": {
            "mock": "demo-mock",
            "ollama": config.OLLAMA_MODEL,
            "openai": config.LLM_MODEL,
        }.get(config.LLM_PROVIDER, "?"),
    }


# ---------------------------------------------------------------- ollama
def _ollama_chat(system: str, user: str, schema: dict | None = None) -> str:
    payload = {
        "model": config.OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        # 关闭思考模式可加速结构化输出（qwen3 系列支持）
        "think": False,
    }
    # 结构化输出：语法约束解码，保证合法 JSON（对量化小模型尤其重要）
    if schema is not None:
        payload["format"] = schema
    try:
        resp = httpx.post(
            f"{config.OLLAMA_BASE_URL.rstrip('/')}/api/chat",
            json=payload,
            timeout=config.LLM_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"]
    except httpx.HTTPError as e:
        raise LLMError(f"Ollama 调用失败（服务是否启动？模型是否已 pull？）: {e}") from e


# ---------------------------------------------------------------- openai 兼容
def _openai_chat(system: str, user: str) -> str:
    if not config.LLM_API_KEY:
        raise LLMError("openai 通道需要设置环境变量 LLM_API_KEY")
    try:
        resp = httpx.post(
            f"{config.LLM_BASE_URL.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {config.LLM_API_KEY}"},
            json={
                "model": config.LLM_MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.3,
            },
            timeout=config.LLM_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except httpx.HTTPError as e:
        raise LLMError(f"云 API 调用失败: {e}") from e


# ---------------------------------------------------------------- mock
def _mock_chat(system: str, user: str) -> str:
    """演示通道：根据 prompt 关键词返回结构合理的假结果，跑通全流程用。

    真实项目应该是高质量的：mock 返回内容明确标注 DEMO，避免和真实模型混淆。
    """
    if "任务拆解" in system or "拆解" in user[:100]:
        return json.dumps({
            "summary": "[DEMO] 按调研→设计→实现→测试→交付的标准节奏拆解为 5 个天级任务",
            "tasks": [
                {
                    "title": "项目调研与需求梳理",
                    "description": "通读项目描述，明确边界，输出关键问题清单",
                    "deliverable_type": "document",
                    "acceptance": ["覆盖项目目标的所有关键点", "输出问题清单且无歧义"],
                    "skill_tags": ["调研", "文档"],
                    "est_hours": 4, "difficulty": 2, "depends_on": [], "priority": "P1",
                },
                {
                    "title": "方案设计",
                    "description": "基于调研结论产出技术/业务方案",
                    "deliverable_type": "document",
                    "acceptance": ["方案可落地", "已识别主要风险"],
                    "skill_tags": ["设计", "文档"],
                    "est_hours": 6, "difficulty": 3, "depends_on": ["项目调研与需求梳理"], "priority": "P1",
                },
                {
                    "title": "核心功能实现",
                    "description": "按方案完成主体实现",
                    "deliverable_type": "code",
                    "acceptance": ["自测通过", "代码可读"],
                    "skill_tags": ["开发"],
                    "est_hours": 8, "difficulty": 4, "depends_on": ["方案设计"], "priority": "P0",
                },
                {
                    "title": "测试与验收",
                    "description": "对照验收标准逐条验证",
                    "deliverable_type": "document",
                    "acceptance": ["全部验收项有结论", "缺陷有记录"],
                    "skill_tags": ["测试"],
                    "est_hours": 6, "difficulty": 3, "depends_on": ["核心功能实现"], "priority": "P1",
                },
                {
                    "title": "交付文档与总结",
                    "description": "整理交付物，沉淀经验",
                    "deliverable_type": "document",
                    "acceptance": ["文档完整", "风险和后续事项明确"],
                    "skill_tags": ["文档"],
                    "est_hours": 4, "difficulty": 2, "depends_on": ["测试与验收"], "priority": "P2",
                },
            ],
        }, ensure_ascii=False)

    if "评估" in system or "评分" in system:
        # 用提交内容长度做一个朴素的演示评分，仅为了跑通闭环
        m = re.search(r"交付物内容如下：\s*(.*?)\s*$", user, re.S)
        content = m.group(1) if m else user
        length = len(content.strip())
        quality = min(95, 40 + length // 20)
        efficiency = min(95, 50 + length // 40)
        return json.dumps({
            "quality_score": quality,
            "efficiency_score": efficiency,
            "feedback": f"[DEMO] 演示评分（基于提交长度 {length} 字）。接入真实模型后会按 TDL 验收标准逐条评估。",
        }, ensure_ascii=False)

    return "[DEMO] mock 通道仅支持任务拆解与交付评估两类请求。"


# ---------------------------------------------------------------- JSON 解析
def parse_json(text: str) -> dict | list:
    """从 LLM 文本中稳健地提取 JSON（容忍 ```json 代码块、前后废话）。"""
    text = text.strip()
    # 去掉 <think>...</think>（qwen3 思考模式）
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    # 去掉 markdown 代码块
    fenced = re.findall(r"```(?:json)?\s*(.*?)```", text, flags=re.S)
    candidates = fenced + [text]

    for cand in candidates:
        cand = cand.strip()
        if not cand:
            continue
        try:
            return json.loads(cand)
        except json.JSONDecodeError:
            # 尝试截取第一个 { 或 [ 到最后一个 } 或 ]
            for l, r in (("{", "}"), ("[", "]")):
                s, e = cand.find(l), cand.rfind(r)
                if s != -1 and e > s:
                    try:
                        return json.loads(cand[s:e + 1])
                    except json.JSONDecodeError:
                        continue
    raise LLMError(f"无法从 LLM 输出中解析 JSON:\n{text[:500]}")
