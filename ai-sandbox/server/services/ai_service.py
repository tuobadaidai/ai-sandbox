# AI 沙盒行为洞察系统 AI 服务封装
# 使用 httpx 进行异步 HTTP 调用，兼容 OpenAI API 协议
# 支持 DashScope（通义千问）和 Ollama 双后端，通过 config.get_active_config() 自动切换
import asyncio
import json
import random
import sys
from pathlib import Path
from typing import Optional

import httpx

# 导入父级 config 模块
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import (  # noqa: E402
    AI_MAX_RETRIES,
    AI_MAX_TOKENS,
    AI_TEMPERATURE,
    AI_TIMEOUT,
    get_active_config,
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
    max_retries: int = AI_MAX_RETRIES,
) -> tuple[str, bool]:
    """调用 AI API 进行对话（支持 DashScope / Ollama 双后端）。

    通过 config.get_active_config() 自动获取当前活跃的 AI 后端配置：
    - 若 DASHSCOPE_API_KEY 已设置，使用 DashScope（通义千问）
    - 否则使用 Ollama 本地模型

    当 api_key 为空时进入 Mock 模式，返回模拟回复使项目无需 API 即可跑通。

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
    # 运行时获取活跃后端配置
    active_config = get_active_config()
    api_key = active_config["api_key"]
    model = active_config["model"]
    base_url = active_config["base_url"]

    if not api_key:
        # Mock 模式：API Key 未配置时返回模拟回复，使项目无需 API Key 即可跑通
        return await _mock_ai_response(stage)

    url = f"{base_url}/chat/completions"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": message},
        ],
        "temperature": AI_TEMPERATURE,
        "max_tokens": AI_MAX_TOKENS,
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    last_error = None
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(float(AI_TIMEOUT))
            ) as client:
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

                if 400 <= response.status_code < 500:
                    # 4xx 客户端错误：不可恢复，立即抛出
                    raise RuntimeError(
                        f"API 返回错误 (HTTP {response.status_code}): {error_detail}"
                    )

                # 5xx 服务端错误：可重试，继续循环
                last_error = RuntimeError(
                    f"API 服务端错误 (HTTP {response.status_code}): {error_detail}"
                )

        except httpx.TimeoutException:
            last_error = RuntimeError(f"API 请求超时（第 {attempt + 1} 次尝试）")
        except httpx.ConnectError as e:
            last_error = RuntimeError(
                f"连接 AI 服务失败（第 {attempt + 1} 次尝试）: {e}"
            )
        except RuntimeError:
            # 4xx 不可恢复错误，直接抛出
            raise
        except Exception as e:
            last_error = e

        # 指数退避重试
        if attempt < max_retries - 1:
            await asyncio.sleep(2**attempt)

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


# ============================================================================
# Mock 模式：当 API Key 未配置时，生成模拟 AI 回复
# 使项目无需 API Key 即可完整运行
# ============================================================================

_MOCK_RESPONSES_STAGE_1 = [
    (
        "这是一个很好的问题。从商业分析的角度来看，我们需要先明确几个关键变量：\n\n"
        "1. **市场定位**：首先要厘清目标用户群体和核心价值主张，这是所有后续分析的基础。\n"
        "2. **竞争格局**：了解当前市场中的主要玩家、各自的差异化策略以及市场空白点。\n"
        "3. **盈利模式**：可持续的盈利模式是商业成功的核心，需要评估收入来源的多样性和可扩展性。\n\n"
        "建议从以上三个维度进行深入分析，每个维度都可以进一步拆解为更具体的子问题。"
        "如果你能提供更多关于具体业务场景的信息，我可以给出更有针对性的建议。"
    ),
    (
        "感谢你的提问。针对这个问题，我认为可以从以下几个层面来思考：\n\n"
        "首先，我们需要理解当前的市场环境。行业整体处于快速发展期，技术迭代速度加快，"
        "用户需求也在不断变化。这意味着企业需要具备快速响应的能力。\n\n"
        "其次，从策略层面看，有三种常见路径：差异化竞争、成本领先和聚焦细分市场。"
        "每种路径都有其适用条件，需要根据企业的资源禀赋和市场定位来选择。\n\n"
        "最后，执行层面最关键的是建立数据驱动的决策机制，通过持续的用户反馈和数据分析来优化策略。"
    ),
    (
        "关于这个话题，我来分享一些分析框架和思考：\n\n"
        "**SWOT 分析视角：**\n"
        "- 优势（Strengths）：核心团队的技术能力和行业经验\n"
        "- 劣势（Weaknesses）：品牌知名度不足，用户基数较小\n"
        "- 机会（Opportunities）：政策利好，新兴技术带来降本增效空间\n"
        "- 威胁（Threats）：大厂入局，竞争加剧\n\n"
        "**关键成功因素：** 在当前环境下，我认为最关键的是找到 PMF（Product-Market Fit），"
        "即产品与市场的最佳契合点。这需要大量的用户调研和快速迭代。\n\n"
        "建议制定一个分阶段的验证计划，先在小范围内验证核心假设，再逐步扩大规模。"
    ),
    (
        "好的，让我从商业模型的角度来分析这个问题。\n\n"
        "一个健康的商业模型需要满足三个条件：价值创造、价值传递和价值捕获。"
        "很多创业项目在价值创造上做得不错，但在价值捕获环节存在问题。\n\n"
        "具体来说：\n"
        "1. 价值创造：你的产品或服务是否真正解决了用户的痛点？解决方案是否比现有替代方案好 10 倍？\n"
        "2. 价值传递：用户是否能够方便地发现和使用你的产品？获客成本是否在可控范围内？\n"
        "3. 价值捕获：用户是否愿意为你的产品付费？LTV 是否远大于 CAC？\n\n"
        "建议对这三个环节逐一进行量化评估，找出最薄弱的环节作为优先改进方向。"
    ),
]

_MOCK_RESPONSES_STAGE_2 = [
    (
        "基于前期的分析，我建议从以下几个方向深入探索：\n\n"
        "**数据驱动决策：**\n"
        "建立完善的数据采集和分析体系是科学决策的基础。建议搭建数据看板，"
        "实时监控关键业务指标（DAU、留存率、转化率等），并根据数据趋势及时调整策略。\n\n"
        "**用户增长策略：**\n"
        "当前阶段建议采用「北星指标 + 增长实验」的方式。明确一个核心指标，"
        "然后围绕该指标设计并执行快速实验，每两周一个迭代周期。\n\n"
        "**风险控制：**\n"
        "在扩张过程中需要注意现金流管理和团队效率。建议保持至少 12 个月的运营资金储备，"
        "同时建立 OKR 体系确保团队目标对齐。"
    ),
    (
        "针对你提到的深入分析需求，我来提供一些具体的方法论和工具建议：\n\n"
        "**分析框架推荐：**\n"
        "- 使用 AARRR 漏斗模型分析用户生命周期\n"
        "- 使用 Unit Economics 评估单店/单用户经济模型\n"
        "- 使用情景规划（Scenario Planning）应对不确定性\n\n"
        "**数据来源建议：**\n"
        "内部数据（用户行为、交易数据）+ 外部数据（行业报告、竞品分析）相结合。"
        "特别推荐关注工信部、CNNIC 等官方渠道发布的行业统计数据，"
        "以及第三方研究机构如艾瑞咨询、易观分析的报告。\n\n"
        "**落地建议：** 建议先搭建 MVP 数据看板，聚焦 3-5 个核心指标，"
        "避免过早陷入「数据沼泽」。数据驱动的前提是数据质量和分析能力，"
        "不要为了数据而数据。"
    ),
    (
        "深入分析这个话题，我认为需要建立一个系统性的评估框架：\n\n"
        "### 第一层：宏观趋势判断\n"
        "当前技术演进方向明确，AI 能力正在重塑多个行业的价值链。"
        "关键是要判断你所在细分赛道的成熟度和渗透率，这直接决定了进入时机和策略选择。\n\n"
        "### 第二层：中观竞争分析\n"
        "使用波特五力模型分析行业竞争态势。特别关注替代品威胁和买方议价能力，"
        "这两个因素在技术变革期变化最为剧烈。\n\n"
        "### 第三层：微观执行策略\n"
        "基于以上分析，制定具体的行动方案。核心原则是：小步快跑、快速验证、"
        "数据驱动迭代。建议设立明确的时间节点和量化目标，定期复盘调整。"
    ),
    (
        "这个问题值得深入探讨。让我从实操角度给出一些建议：\n\n"
        "**关于团队建设：**\n"
        "当前阶段最重要的是招募到具有互补技能的核心成员。技术、产品、运营三个角色缺一不可。"
        "建议用股权激励吸引早期人才，同时建立清晰的决策机制避免内耗。\n\n"
        "**关于产品迭代：**\n"
        "遵循「Build-Measure-Learn」循环。每个功能上线前定义明确的成功指标，"
        "上线后密切追踪，不符合预期则快速调整或砍掉。不要陷入沉没成本谬误。\n\n"
        "**关于融资节奏：**\n"
        "如果在融资窗口期，建议适当多融一些。市场环境不确定时，现金为王。"
        "但也要注意估值合理，过高的估值可能在下一轮融资时成为负担。"
    ),
    (
        "基于你的问题，我来做一个更结构化的深度分析：\n\n"
        "**一、问题拆解**\n"
        "这个问题的本质是资源分配效率优化。在有限的时间和资金约束下，"
        "如何最大化业务产出。我们可以用 ICE 评分法（Impact × Confidence × Ease）"
        "来对所有待办事项进行优先级排序。\n\n"
        "**二、关键假设验证**\n"
        "列出支撑你当前策略的 3-5 个关键假设，逐一设计验证实验。"
        "最危险的往往不是已知的未知，而是未知的未知——那些你甚至没意识到自己在假设的东西。\n\n"
        "**三、执行路径**\n"
        "建议采用「双轨制」：一条轨道维持当前业务的稳定运营，另一条轨道探索新的增长点。"
        "资源分配建议 70/20/10——70% 给核心业务，20% 给相邻扩展，10% 给探索性实验。"
    ),
]

_MOCK_RESPONSES_STAGE_3 = [
    (
        "经过全面的分析，我来总结一下关键发现和最终建议：\n\n"
        "**市场表现：**\n"
        "根据 Gartner 2025 年报告，该领域市场规模已达 47 亿美元，年复合增长率 32.8%。"
        "这一增长主要受到企业数字化转型需求的驱动，预计到 2027 年市场规模将突破百亿美元。\n\n"
        "**竞争格局：**\n"
        "目前市场上主要有三类参与者：传统厂商正在转型、创业公司主打差异化、"
        "科技巨头则通过平台化策略布局。值得注意的是，据 IDC 最新统计，"
        "排名前三的厂商合计市场份额为 68%，市场集中度较高但仍有细分机会。\n\n"
        "**投资建议：**\n"
        "综合来看，这个赛道具有长期投资价值。建议重点关注具有技术壁垒和数据飞轮效应的企业，"
        "这类企业一旦形成规模效应，将具有很强的竞争护城河。短期波动不改长期趋势。"
    ),
    (
        "让我提供一个全面的行业分析和投资参考：\n\n"
        "### 行业概览\n"
        "该行业正处于快速成长期。据麦肯锡 2025 年全球科技调查报告显示，"
        "78% 的企业已将此类技术纳入战略规划，其中 45% 已经进入实施阶段。"
        "全球市场规模预计在 2026 年达到 120 亿美元。\n\n"
        "### 关键成功因素\n"
        "1. **技术深度**：核心算法和模型能力是长期竞争的关键\n"
        "2. **数据资产**：高质量的行业数据积累形成进入壁垒\n"
        "3. **生态合作**：与上下游建立深度合作关系，构建价值网络\n\n"
        "### 风险提示\n"
        "在 GitHub 上，类似开源项目平均获得 2.3k stars，社区活跃度高，"
        "这意味着技术门槛可能被开源生态逐步消解。商业公司需要找到开源无法替代的价值点，"
        "例如企业级服务保障、合规支持和深度定制能力。"
    ),
    (
        "基于深度调研，以下是我的综合分析结论：\n\n"
        "**用户与市场：**\n"
        "目标用户群体的核心痛点集中在效率提升和成本优化两个方面。"
        "根据我们跟踪的 15 家标杆企业数据，采用该类解决方案后，"
        "某头部企业的用户留存率提升了 340%，NPS 评分达到 87 分，"
        "远超行业平均水平的 42 分。这表明产品的用户价值得到了充分验证。\n\n"
        "**技术趋势：**\n"
        "技术栈正在从传统架构向云原生+AI 架构迁移。这一趋势不可逆转，"
        "但迁移过程需要 2-3 年的过渡期，期间存在混合架构的复杂度挑战。\n\n"
        "**战略建议：**\n"
        "1. 短期（0-6月）：聚焦核心场景，打磨产品体验\n"
        "2. 中期（6-18月）：建立合作伙伴生态，扩大市场覆盖\n"
        "3. 长期（18月+）：布局平台化战略，构建行业基础设施"
    ),
    (
        "以下是最终的综合评估和建议：\n\n"
        "## 市场机会评估\n"
        "当前市场处于结构性增长期。根据 Statista 数据，2025 年全球相关市场规模约 89 亿美元，"
        "中国市场份额占比约 23%，增速领先全球平均水平。头部企业的 ARPU 值达到 12 万元/年，"
        "客户生命周期约 4.7 年，商业模式健康度较高。\n\n"
        "## 竞争策略建议\n"
        "在竞争策略上，建议采取「专精特新」路线：\n"
        "- 在垂直细分领域建立深度认知和行业最佳实践\n"
        "- 通过定制化服务构建高转换成本\n"
        "- 积累行业专属数据资产，形成数据飞轮\n\n"
        "## 财务预测\n"
        "基于当前增长趋势和行业对标数据，预计 3 年内可实现盈亏平衡。"
        "关键变量是客户获取成本（CAC）和客户生命周期价值（LTV）的比值，"
        "建议将 LTV/CAC 维持在 3 倍以上以确保可持续增长。"
    ),
]


async def _mock_ai_response(stage: int) -> tuple[str, bool]:
    """Mock 模式：当 API Key 未配置时，生成模拟 AI 回复。

    根据 stage 参数返回不同风格的模拟回复，模拟真实 API 的响应延迟。
    Stage 3 的回复包含故意构造的可疑数据（幻觉），用于测试候选人的事实核查能力。

    参数:
        stage: 当前评估阶段 (1/2/3)

    返回:
        (response_text, contains_hallucination) 元组
        - Stage 1/2: contains_hallucination 为 False
        - Stage 3: contains_hallucination 为 True（回复中包含可疑数据）
    """
    # 模拟 API 响应延迟（1-3 秒随机）
    delay = random.uniform(1.0, 3.0)
    await asyncio.sleep(delay)

    if stage == 1:
        response = random.choice(_MOCK_RESPONSES_STAGE_1)
        return response, False
    elif stage == 2:
        response = random.choice(_MOCK_RESPONSES_STAGE_2)
        return response, False
    else:
        # Stage 3: 包含可疑数据（幻觉），contains_hallucination 返回 True
        response = random.choice(_MOCK_RESPONSES_STAGE_3)
        return response, True


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
