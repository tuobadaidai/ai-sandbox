# AI 沙盒行为洞察系统 AI 服务封装
# 重构版：业务逻辑与 AI 后端解耦
# - AI Provider 抽象层（ai_provider.py）负责实际 API 调用
# - 本模块负责业务逻辑：幻觉注入、错误兜底
import random
from typing import Optional

from .ai_provider import BaseAIProvider, create_provider

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

# ============================================================================
# 全局 Provider 单例（延迟初始化）
# ============================================================================
_provider: Optional[BaseAIProvider] = None


def _get_provider() -> BaseAIProvider:
    """获取全局 AI Provider 单例"""
    global _provider
    if _provider is None:
        _provider = create_provider()
    return _provider


async def chat_with_ai(
    message: str,
    stage: int,
    conversation_id: Optional[str] = None,
    max_retries: int = 3,
) -> tuple[str, bool]:
    """调用 AI 进行对话，自动选择后端并在 Stage 3 注入幻觉。

    通过 ai_provider.create_provider() 自动获取合适的 AI 后端：
    - 若 DASHSCOPE_API_KEY 已设置 → DashScope
    - 若 AI_API_KEY 已设置 → Ollama
    - 否则 → Mock 模式

    参数:
        message: 用户输入的消息文本
        stage: 当前评估阶段 (1/2/3)
        conversation_id: 对话会话 ID（可选）
        max_retries: 最大重试次数（暂未使用，由 Provider 内部处理）

    返回:
        (response_text, contains_hallucination) 元组
    """
    provider = _get_provider()

    try:
        content = await provider.chat(
            message=message,
            stage=stage,
            system_prompt=SYSTEM_PROMPT,
            conversation_id=conversation_id,
        )

        # Stage 3: 尝试注入幻觉数据
        if stage == 3:
            return _inject_hallucination(content)
        else:
            return content, False

    except Exception as e:
        # 兜底：所有 Provider 异常都返回友好提示
        return (
            f"抱歉，AI 服务暂时不可用，请稍后重试。"
            f"（错误详情: {e}）",
            False,
        )


# ============================================================================
# 幻觉注入逻辑
# ============================================================================

def _inject_hallucination(content: str) -> tuple[str, bool]:
    """在 AI 回复中注入一条幻觉数据。

    注入策略:
    - 要求 AI 回复长度 > 200 字符才进行注入
    - 按关键词匹配选择最相关的种子数据
    - 将注入语句附加到回复末尾的下一段（模拟自然的多段落回复）

    参数:
        content: 原始 AI 回复文本

    返回:
        (modified_content, True) 如果成功注入
        (original_content, False) 如果回复太短或无法匹配关键词
    """
    if len(content) <= 200:
        return content, False

    # 尝试按关键词匹配种子数据
    matched_seeds = [seed for seed in HALLUCINATION_SEEDS if seed["keyword"] in content]

    # 如果没有关键词匹配，随机选择一个种子
    seed = random.choice(matched_seeds) if matched_seeds else random.choice(HALLUCINATION_SEEDS)

    injection = seed["injection"]

    # 注入策略: 在回复末尾追加一条新段落，模拟自然补充说明
    randomized_content = _insert_near_keyword_or_end(content, seed["keyword"], injection)
    return randomized_content, True


def _insert_near_keyword_or_end(text: str, keyword: str, injection: str) -> str:
    """在文本中靠近关键词的自然位置插入幻觉语句。

    优先在包含关键词的段落之后插入，如果找不到则追加到文本末尾。

    参数:
        text: 原始文本
        keyword: 用于定位的关键词
        injection: 要注入的内容

    返回:
        注入后的文本
    """
    paragraphs = text.split("\n\n")
    target_idx = -1
    for i, para in enumerate(paragraphs):
        if keyword in para:
            target_idx = i
            break

    if target_idx >= 0 and target_idx < len(paragraphs) - 1:
        paragraphs.insert(target_idx + 1, injection)
        return "\n\n".join(paragraphs)
    else:
        return text + "\n\n" + injection
