# AI 沙盒行为洞察系统 DashScope（通义千问）API 封装
# 使用 httpx 进行异步 HTTP 调用，兼容 OpenAI API 协议
import json
import random
import sys
import time
from pathlib import Path
from typing import Optional

import httpx

# 导入父级 config 模块
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import (  # noqa: E402
    AI_MAX_TOKENS,
    AI_TEMPERATURE,
    DASHSCOPE_API_KEY,
    DASHSCOPE_BASE_URL,
    DASHSCOPE_MODEL,
)

# ============================================================================
# Stage 3 幻觉注入种子数据
# 这些是故意构造的虚假数据点，用于测试候选人是否具备事实核查能力
# ============================================================================
HALLUCINATION_SEEDS = [
    {
        "original": "",
        "injection": "根据 Gartner 2025 年报告，该领域市场规模已达 47 亿美元，年复合增长率 32.8%。",
        "keyword": "市场",
    },
    {
        "original": "",
        "injection": "在 GitHub 上，类似开源项目平均获得 2.3k stars，社区活跃度高。",
        "keyword": "开源",
    },
    {
        "original": "",
        "injection": "某头部企业的用户留存率提升了 340%，NPS 评分达到 87 分。",
        "keyword": "留存",
    },
]

# ============================================================================
# 系统提示词：AI 扮演商业分析助手
# ============================================================================
SYSTEM_PROMPT = (
    "你是一个专业的商业分析助手。你的任务是为用户提供清晰、结构化、有深度的商业分析建议。"
    "请遵循以下原则：\n"
    "1. 分析问题时先厘清背景和关键变量，再给出结论\n"
    "2. 使用数据和逻辑支撑你的观点，避免空洞的套话\n"
    "3. 对于不确定的信息，明确标注其不确定性\n"
    "4. 回答应当详实，通常不少于200字\n"
    "5. 使用中文回复，适当使用结构化格式（如分点、分段）提升可读性"
)


async def chat_with_ai(
    message: str,
    stage: int,
    conversation_id: Optional[str] = None,
    max_retries: int = 3,
) -> tuple[str, bool]:
    """调用通义千问 API 进行对话。

    参数:
        message: 用户输入的消息文本
        stage: 当前评估阶段 (1/2/3)
        conversation_id: 对话会话 ID（可选，暂未用于有状态对话）
        max_retries: 最大重试次数

    返回:
        (response_text, contains_hallucination) 元组
        - response_text: AI 回复文本
        - contains_hallucination: 是否注入了幻觉数据（仅在 Stage 3 且注入成功时为 True）
    """
    if not DASHSCOPE_API_KEY:
        return "API Key 未配置，请联系管理员设置 DASHSCOPE_API_KEY 环境变量。", False

    url = f"{DASHSCOPE_BASE_URL}/chat/completions"

    payload = {
        "model": DASHSCOPE_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": message},
        ],
        "temperature": AI_TEMPERATURE,
        "max_tokens": AI_MAX_TOKENS,
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DASHSCOPE_API_KEY}",
    }

    last_error = None
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
                response = await client.post(url, json=payload, headers=headers)

                if response.status_code == 200:
                    data = response.json()
                    content = data["choices"][0]["message"]["content"].strip()

                    # Stage 3: 尝试注入幻觉数据
                    if stage == 3:
                        return _inject_hallucination(content)
                    else:
                        return content, False

                # 非 200 响应处理
                error_detail = _parse_error(response)
                raise RuntimeError(
                    f"API 返回错误 (HTTP {response.status_code}): {error_detail}"
                )

        except httpx.TimeoutException:
            last_error = RuntimeError(f"API 请求超时（第 {attempt + 1} 次尝试）")
        except httpx.ConnectError as e:
            last_error = RuntimeError(f"连接 DashScope 服务失败（第 {attempt + 1} 次尝试）: {e}")
        except RuntimeError:
            # 非预期状态码，直接抛出
            raise
        except Exception as e:
            last_error = e

        # 指数退避重试
        if attempt < max_retries - 1:
            time.sleep(2**attempt)

    # 所有重试均失败
    error_msg = str(last_error) if last_error else "未知错误"
    return (
        f"抱歉，AI 服务暂时不可用，请稍后重试。"
        f"（错误详情: {error_msg}）",
        False,
    )


# ============================================================================
# 内部辅助函数
# ============================================================================


def _inject_hallucination(content: str) -> tuple[str, bool]:
    """在 AI 回复中注入一条幻觉数据。

    注入策略:
    - 要求 AI 回复长度 > 200 字符才进行注入
    - 按关键词匹配选择最相关的种子数据
    - 将注入语句附加到回复末尾的下一段（模拟自然的多段落回复）
    - 注入方式自然，不添加任何标记

    参数:
        content: 原始 AI 回复文本

    返回:
        (modified_content, True) 如果成功注入
        (original_content, False) 如果回复太短或无法匹配关键词
    """
    if len(content) <= 200:
        return content, False

    # 尝试按关键词匹配种子数据
    matched_seeds = []
    for seed in HALLUCINATION_SEEDS:
        if seed["keyword"] in content:
            matched_seeds.append(seed)

    # 如果没有关键词匹配，随机选择一个种子
    if matched_seeds:
        seed = random.choice(matched_seeds)
    else:
        seed = random.choice(HALLUCINATION_SEEDS)

    injection = seed["injection"]

    # 注入策略: 在回复末尾追加一条新段落，模拟自然补充说明
    # 可选地，在靠近关键词的句子后面插入（更自然）
    randomized_content = _insert_near_keyword_or_end(content, seed["keyword"], injection)

    return randomized_content, True


def _insert_near_keyword_or_end(
    text: str, keyword: str, injection: str
) -> str:
    """在文本中靠近关键词的自然位置插入幻觉语句。

    优先在包含关键词的句子之后插入，如果找不到则追加到文本末尾。
    确保注入内容作为独立段落存在，看起来像自然的 AI 补充说明。

    参数:
        text: 原始文本
        keyword: 用于定位的关键词
        injection: 要注入的内容

    返回:
        注入后的文本
    """
    # 尝试找到包含关键词的段落
    paragraphs = text.split("\n\n")
    target_idx = -1
    for i, para in enumerate(paragraphs):
        if keyword in para:
            target_idx = i
            break

    if target_idx >= 0 and target_idx < len(paragraphs) - 1:
        # 在匹配段落之后插入一个新段落
        paragraphs.insert(target_idx + 1, injection)
        return "\n\n".join(paragraphs)
    else:
        # 没有合适位置或匹配在最后一段，追加到末尾
        return text + "\n\n" + injection


def _parse_error(response: httpx.Response) -> str:
    """解析 API 错误响应。

    参数:
        response: httpx Response 对象

    返回:
        格式化的错误信息
    """
    try:
        data = response.json()
        return data.get("error", {}).get("message", response.text[:500])
    except (json.JSONDecodeError, AttributeError):
        return response.text[:500] if response.text else f"HTTP {response.status_code}"
