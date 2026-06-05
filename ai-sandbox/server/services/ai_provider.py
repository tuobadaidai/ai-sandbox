# AI 沙盒行为洞察系统 - AI Provider 抽象层
# 统一 AI 后端接口，支持 DashScope / Ollama / Mock 三种模式
# 新增 provider 只需继承 BaseAIProvider 并实现 chat() 方法

import asyncio
import json
import random
from abc import ABC, abstractmethod
from typing import Any, Optional

import httpx

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import (
    DASHSCOPE_API_KEY, DASHSCOPE_MODEL, DASHSCOPE_BASE_URL,
    AI_API_KEY, AI_MODEL, AI_BASE_URL,
    AI_MAX_RETRIES, AI_MAX_TOKENS, AI_TEMPERATURE, AI_TIMEOUT,
)


# ============================================================================
# 基础 Provider 接口
# ============================================================================

class BaseAIProvider(ABC):
    """AI Provider 基类，所有后端必须实现 chat() 方法"""

    @abstractmethod
    async def chat(
        self,
        message: str,
        stage: int,
        system_prompt: str,
        conversation_id: Optional[str] = None,
    ) -> str:
        """发送消息并返回 AI 回复文本

        参数:
            message: 用户消息
            stage: 当前评估阶段
            system_prompt: 系统提示词
            conversation_id: 会话 ID（可选）

        返回:
            AI 回复文本
        """
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider 名称，用于日志和调试"""
        ...


# ============================================================================
# DashScope Provider（通义千问）
# ============================================================================

class DashScopeProvider(BaseAIProvider):
    """阿里云 DashScope（通义千问）AI 后端"""

    def __init__(self, api_key: str = None, model: str = None, base_url: str = None):
        self.api_key = api_key or DASHSCOPE_API_KEY
        self.model = model or DASHSCOPE_MODEL
        self.base_url = base_url or DASHSCOPE_BASE_URL

    @property
    def name(self) -> str:
        return f"DashScope({self.model})"

    async def chat(
        self,
        message: str,
        stage: int,
        system_prompt: str,
        conversation_id: Optional[str] = None,
    ) -> str:
        return await self._call_openai_api(
            message=message,
            system_prompt=system_prompt,
            model=self.model,
            api_key=self.api_key,
            base_url=self.base_url,
        )

    async def _call_openai_api(
        self,
        message: str,
        system_prompt: str,
        model: str,
        api_key: str,
        base_url: str,
    ) -> str:
        """调用 OpenAI 兼容 API"""
        url = f"{base_url}/chat/completions"
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
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
        for attempt in range(AI_MAX_RETRIES):
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(float(AI_TIMEOUT))
                ) as client:
                    response = await client.post(url, json=payload, headers=headers)

                    if response.status_code == 200:
                        data = response.json()
                        return data["choices"][0]["message"]["content"].strip()

                    error_detail = self._parse_error(response)

                    if 400 <= response.status_code < 500:
                        raise RuntimeError(
                            f"API 返回错误 (HTTP {response.status_code}): {error_detail}"
                        )

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
                raise
            except Exception as e:
                last_error = e

            if attempt < AI_MAX_RETRIES - 1:
                await asyncio.sleep(2 ** attempt)

        raise RuntimeError(
            f"AI 服务不可用: {str(last_error) if last_error else '未知错误'}"
        )

    @staticmethod
    def _parse_error(response: httpx.Response) -> str:
        try:
            data = response.json()
            return data.get("error", {}).get("message", response.text[:500])
        except (json.JSONDecodeError, AttributeError):
            return response.text[:500] if response.text else f"HTTP {response.status_code}"


# ============================================================================
# Ollama Provider（本地模型）
# ============================================================================

class OllamaProvider(BaseAIProvider):
    """Ollama 本地 AI 后端（OpenAI 兼容协议）"""

    def __init__(self, api_key: str = None, model: str = None, base_url: str = None):
        self.api_key = api_key or AI_API_KEY
        self.model = model or AI_MODEL
        self.base_url = base_url or AI_BASE_URL

    @property
    def name(self) -> str:
        return f"Ollama({self.model})"

    async def chat(
        self,
        message: str,
        stage: int,
        system_prompt: str,
        conversation_id: Optional[str] = None,
    ) -> str:
        # Ollama 也走 OpenAI 兼容协议，复用 DashScope 的 API 调用逻辑
        provider = DashScopeProvider()
        return await provider._call_openai_api(
            message=message,
            system_prompt=system_prompt,
            model=self.model,
            api_key=self.api_key,
            base_url=self.base_url,
        )


# ============================================================================
# Mock Provider（无需 API Key）
# ============================================================================

_MOCK_RESPONSES = {
    1: [
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
    ],
    2: [
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
            "特别推荐关注工信部、CNNIC 等官方渠道发布的行业统计数据。\n\n"
            "**落地建议：** 建议先搭建 MVP 数据看板，聚焦 3-5 个核心指标。"
        ),
    ],
    3: [
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
            "综合来看，这个赛道具有长期投资价值。建议重点关注具有技术壁垒和数据飞轮效应的企业。"
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
            "这意味着技术门槛可能被开源生态逐步消解。"
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
            "但迁移过程需要 2-3 年的过渡期。\n\n"
            "**战略建议：**\n"
            "1. 短期（0-6月）：聚焦核心场景，打磨产品体验\n"
            "2. 中期（6-18月）：建立合作伙伴生态，扩大市场覆盖\n"
            "3. 长期（18月+）：布局平台化战略，构建行业基础设施"
        ),
    ],
}


class MockProvider(BaseAIProvider):
    """Mock AI Provider，无需 API Key 即可运行"""

    @property
    def name(self) -> str:
        return "Mock"

    async def chat(
        self,
        message: str,
        stage: int,
        system_prompt: str,
        conversation_id: Optional[str] = None,
    ) -> str:
        # 模拟 API 响应延迟
        delay = random.uniform(1.0, 3.0)
        await asyncio.sleep(delay)

        stage_responses = _MOCK_RESPONSES.get(stage, _MOCK_RESPONSES[1])
        return random.choice(stage_responses)


# ============================================================================
# Provider 工厂
# ============================================================================

# 运行时配置覆盖（由 ConfigService 热更新写入）
_runtime_overrides = {
    "provider": None,       # "dashscope" / "ollama" / "mock"
    "dashscope": {},        # 覆盖 dashscope 配置
    "ollama": {},           # 覆盖 ollama 配置
    "params": {},           # 覆盖 AI 参数
    "hallucination_rate": None,
}


def update_runtime_config(key: str, value: Any):
    """热更新 AI Provider 运行时配置（由 ConfigService 调用）"""
    global _runtime_overrides
    if key in ("provider", "hallucination_rate"):
        _runtime_overrides[key] = value
    elif key in ("dashscope", "ollama", "params"):
        _runtime_overrides[key] = value
    # provider 或连接参数变更时，重置缓存的 provider 单例
    try:
        from .ai_service import reset_provider
        reset_provider()
    except ImportError:
        pass


def get_active_provider_config() -> dict:
    """获取当前生效的 provider 配置（合并运行时覆盖 + 环境变量）"""
    provider = _runtime_overrides.get("provider")
    if provider == "mock":
        return {"provider": "mock"}
    elif provider == "dashscope" or (provider is None and DASHSCOPE_API_KEY):
        ds = {"api_key": DASHSCOPE_API_KEY, "model": DASHSCOPE_MODEL, "base_url": DASHSCOPE_BASE_URL}
        ds.update(_runtime_overrides.get("dashscope", {}))
        return {"provider": "dashscope", **ds}
    else:
        ol = {"api_key": AI_API_KEY, "model": AI_MODEL, "base_url": AI_BASE_URL}
        ol.update(_runtime_overrides.get("ollama", {}))
        return {"provider": "ollama", **ol}


def create_provider() -> BaseAIProvider:
    """根据配置创建合适的 AI Provider

    优先级：运行时覆盖 > DashScope > Ollama > Mock

    返回:
        BaseAIProvider 实例
    """
    provider = _runtime_overrides.get("provider")

    if provider == "mock":
        return MockProvider()
    elif provider == "dashscope":
        cfg = get_active_provider_config()
        return DashScopeProvider(
            api_key=cfg.get("api_key", DASHSCOPE_API_KEY),
            model=cfg.get("model", DASHSCOPE_MODEL),
            base_url=cfg.get("base_url", DASHSCOPE_BASE_URL),
        )
    elif provider == "ollama":
        cfg = get_active_provider_config()
        return OllamaProvider(
            model=cfg.get("model", AI_MODEL),
            base_url=cfg.get("base_url", AI_BASE_URL),
        )

    # 自动检测（无运行时覆盖时走原逻辑）
    if DASHSCOPE_API_KEY:
        return DashScopeProvider()
    else:
        return OllamaProvider() if AI_BASE_URL else MockProvider()
