# AI 沙盒行为洞察系统 行为分析器
# 将结构化行为事件翻译为叙事文本，并计算 6 维能力得分
import statistics
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# 导入父级 database 模块
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import database as db  # noqa: E402

# ============================================================================
# 反汇编/规划关键词：用于判断候选人是否主动拆解问题
# ============================================================================
DECOMPOSITION_KEYWORDS = ["首先", "第一步", "框架", "拆解", "分", "步骤", "方案", "结构"]

CLARIFICATION_KEYWORDS = ["?", "？", "什么", "哪些", "如何", "怎么", "是否", "请确认", "确认一下"]


# ============================================================================
# 1. 行为事件 → 叙事文本
# ============================================================================


def translate_to_narrative(
    events: list[dict], interactions: list[dict], candidate: Optional[dict]
) -> str:
    """将结构化行为事件和 AI 交互记录翻译为叙事报告文本。

    生成的叙事文本可直接作为 ai-talent-grader Skill 的 Mode C 输入。

    参数:
        events: 行为事件列表（已包含解析后的 metadata 字段）
        interactions: AI 交互记录列表
        candidate: 候选人信息字典（含 name 字段），为 None 时使用 "未知候选人"

    返回:
        格式化的叙事报告文本
    """
    if not events:
        candidate_name = candidate.get("name", "未知候选人") if candidate else "未知候选人"
        return (
            f"=== 候选人行为叙事报告 ===\n"
            f"候选人: {candidate_name}\n"
            f"任务时间: 无数据\n\n"
            f"（该候选人暂无行为事件记录）\n"
        )

    # ---- 基本信息 ----
    candidate_name = candidate.get("name", "未知候选人") if candidate else "未知候选人"
    timestamps = [e.get("timestamp", "") for e in events if e.get("timestamp")]
    first_ts = timestamps[0] if timestamps else "未知"
    last_ts = timestamps[-1] if timestamps else "未知"

    # ---- 按 stage 分组事件 ----
    events_by_stage: dict[int, list[dict]] = defaultdict(list)
    for e in events:
        stage = e.get("stage", 1)
        events_by_stage[stage].append(e)

    # 构建交互索引：按 stage 组织，方便快速查找
    interactions_by_stage: dict[int, list[dict]] = defaultdict(list)
    for inter in interactions:
        stage = inter.get("stage", 1)
        interactions_by_stage[stage].append(inter)

    # ---- 生成报告 ----
    lines: list[str] = []
    lines.append("=== 候选人行为叙事报告 ===")
    lines.append(f"候选人: {candidate_name}")
    lines.append(f"任务时间: {_fmt_ts(first_ts)} ~ {_fmt_ts(last_ts)}")

    stage_names = {1: "模糊需求破局", 2: "动态压力测试", 3: "事实核查与对抗"}

    for stage in sorted(events_by_stage.keys()):
        stage_events = events_by_stage[stage]
        stage_interactions = interactions_by_stage.get(stage, [])
        stage_label = stage_names.get(stage, f"Stage {stage}")
        lines.append("")
        lines.append(f"--- Stage {stage}: {stage_label} ---")
        lines.append("")
        lines.extend(
            _build_stage_narrative(
                stage_events, stage_interactions, _ref_ts(stage_events)
            )
        )

    return "\n".join(lines)


def _build_stage_narrative(
    stage_events: list[dict],
    stage_interactions: list[dict],
    ref_timestamp: Optional[str],
) -> list[str]:
    """为单个阶段构建叙事文本行。

    参数:
        stage_events: 该阶段的所有行为事件
        stage_interactions: 该阶段的所有 AI 交互记录
        ref_timestamp: 参考时间戳，用于计算相对时间 [MM:SS]

    返回:
        叙事文本行列表
    """
    lines: list[str] = []
    prev_prompts: list[str] = []  # 追踪之前的 prompt，用于判断迭代行为
    interaction_index = 0  # 用于按顺序关联 AI 交互

    for event in stage_events:
        event_type = event.get("event_type", "")
        metadata = event.get("metadata", {})
        if isinstance(metadata, str):
            import json
            try:
                metadata = json.loads(metadata)
            except (json.JSONDecodeError, TypeError):
                metadata = {}
        ts = _relative_time(event.get("timestamp", ""), ref_timestamp)

        if event_type == "TASK_START":
            lines.append(f"[{ts}] 候选人开始任务")

        elif event_type == "AI_PROMPT_SEND":
            prompt_text = metadata.get("prompt_text", "") or ""
            prompt_len = metadata.get("prompt_length", len(prompt_text))

            # 分析 prompt 质量
            analysis = _analyze_prompt(prompt_text, prev_prompts)
            lines.append(
                f"[{ts}] 候选人向AI发送prompt（{prompt_len}字，{analysis}）"
            )
            prev_prompts.append(prompt_text)

            # 关联对应的 AI 交互记录
            if interaction_index < len(stage_interactions):
                inter = stage_interactions[interaction_index]
                resp_len = inter.get("response_length", 0)
                lines.append(
                    f"[{ts}] AI返回响应（{resp_len}字）"
                )
                interaction_index += 1

        elif event_type == "AI_OUTPUT_EDIT":
            edit_depth = metadata.get("edit_depth", 0)
            depth_desc = "深度编辑" if edit_depth > 0.5 else "小幅修改"
            lines.append(f"[{ts}] 候选人{depth_desc}了AI输出")

        elif event_type == "AI_OUTPUT_ACCEPT":
            lines.append(f"[{ts}] 候选人直接采纳了AI输出")

        elif event_type == "TEXT_INPUT":
            text_len = metadata.get("text_length", 0)
            lines.append(f"[{ts}] 候选人进行手动编辑（{text_len}字符）")

        elif event_type == "ERROR_ENCOUNTERED":
            error_type = metadata.get("error_type", "未知错误")
            recovered = metadata.get("recovered", False)
            recovery_text = "并成功恢复" if recovered else "尚未解决"
            lines.append(f"[{ts}] 候选人遇到{error_type}，{recovery_text}")

        elif event_type == "UNDO_REDO":
            operation = metadata.get("operation", "undo/redo")
            lines.append(f"[{ts}] 候选人执行了{operation}操作")

        elif event_type == "STAGE_TRANSITION":
            from_stage = metadata.get("from_stage", "?")
            to_stage = metadata.get("to_stage", "?")
            lines.append(f"[{ts}] 候选人从 Stage {from_stage} 进入 Stage {to_stage}")

        elif event_type == "TASK_SUBMIT":
            lines.append(f"[{ts}] 候选人提交了最终答案")

        # 对于其他事件类型（COPY_PASTE, TAB_SWITCH, SCROLL 等），
        # 不生成叙事行，保持报告聚焦于关键行为

    # 如果该阶段没有任何叙事行，添加占位信息
    if not lines:
        lines.append("[--:--] 该阶段无关键行为记录")

    return lines


def _analyze_prompt(prompt_text: str, prev_prompts: list[str]) -> str:
    """分析 prompt 质量，返回简短描述。

    参数:
        prompt_text: 当前 prompt 文本
        prev_prompts: 之前所有的 prompt 文本列表（不包括当前）

    返回:
        分析描述，例如 "展示问题拆解能力" / "提出澄清性问题" / "迭代优化" / "直接提问"
    """
    if not prompt_text:
        return "空prompt"

    has_decomposition = any(kw in prompt_text for kw in DECOMPOSITION_KEYWORDS)
    has_clarification = any(kw in prompt_text for kw in CLARIFICATION_KEYWORDS)

    # 检查是否为迭代 prompt（与之前 prompt 相似但有所修改）
    is_iterative = False
    if prev_prompts:
        last_prompt = prev_prompts[-1]
        similarity = _text_similarity(prompt_text, last_prompt)
        is_iterative = 0.3 < similarity < 0.9  # 相似但不完全相同

    # 按优先级组合分析
    parts = []
    if has_decomposition:
        parts.append("展示问题拆解能力")
    if has_clarification:
        parts.append("提出澄清性问题")
    if is_iterative:
        parts.append("迭代优化")
    if not parts:
        parts.append("直接提问")

    return "，".join(parts)


def _text_similarity(a: str, b: str) -> float:
    """计算两个文本的简单相似度（Jaccard 字符级三元组）。

    参数:
        a, b: 待比较的两个字符串

    返回:
        0.0 ~ 1.0 之间的相似度
    """
    if not a or not b:
        return 0.0

    def tri_grams(s: str) -> set:
        s = s.replace(" ", "")
        return {s[i : i + 3] for i in range(len(s) - 2)}

    ta = tri_grams(a)
    tb = tri_grams(b)
    if not ta or not tb:
        return 0.0
    intersection = ta & tb
    union = ta | tb
    return len(intersection) / len(union)


# ============================================================================
# 2. 6维能力得分计算
# ============================================================================


def calculate_dimension_scores(
    events: list[dict], interactions: list[dict]
) -> dict[str, float]:
    """基于行为事件和 AI 交互计算 6 维能力得分。

    六个维度：
    1. ai_fluency         - AI 流利度
    2. human_ai_judgment  - 人机判断力
    3. architecture_design - 架构设计力
    4. hybrid_orchestration - 混合编排力
    5. cognitive_depth     - 认知深度
    6. problem_modeling    - 问题建模能力

    每个维度得分范围为 1.0 ~ 3.5（上限封顶）。

    参数:
        events: 行为事件列表
        interactions: AI 交互记录列表

    返回:
        包含 6 个维度得分的字典
    """
    # 解析 metadata 字段（确保是 dict 类型）
    parsed_events = _ensure_parsed_metadata(events)

    scores: dict[str, float] = {}

    scores["ai_fluency"] = _calc_ai_fluency(parsed_events, interactions)
    scores["human_ai_judgment"] = _calc_human_ai_judgment(parsed_events)
    scores["architecture_design"] = _calc_architecture_design(parsed_events)
    scores["hybrid_orchestration"] = _calc_hybrid_orchestration(parsed_events)
    scores["cognitive_depth"] = _calc_cognitive_depth(parsed_events)
    scores["problem_modeling"] = _calc_problem_modeling(parsed_events)

    return scores


def _calc_ai_fluency(events: list[dict], interactions: list[dict]) -> float:
    """AI 流利度：评估候选人与 AI 交互的频次、深度和迭代能力。

    指标:
    - prompt 数量
    - 平均 prompt 长度
    - 迭代次数（修改后重复发送的 prompt）
    """
    prompts = [e for e in events if e.get("event_type") == "AI_PROMPT_SEND"]
    if not prompts:
        return 1.0

    # 收集所有 prompt 文本
    prompt_texts = [
        p.get("metadata", {}).get("prompt_text", "") for p in prompts
    ]
    prompt_texts = [t for t in prompt_texts if t]

    if not prompt_texts:
        return 1.0

    # 计算迭代次数：比较相邻 prompt 的相似度
    iteration_count = 0
    for i in range(1, len(prompt_texts)):
        sim = _text_similarity(prompt_texts[i], prompt_texts[i - 1])
        if 0.3 < sim < 0.9:
            iteration_count += 1

    # 平均长度
    avg_length = statistics.mean(len(t) for t in prompt_texts)

    # 计分逻辑
    if iteration_count == 0:
        score = 1.0
    elif 1 <= iteration_count <= 2:
        score = 1.5 + (iteration_count - 1) * 0.5  # 1.5 ~ 2.0
    else:
        # 3+ 次迭代，检查长度变化
        lengths = [len(t) for t in prompt_texts]
        length_variation = max(lengths) - min(lengths) if len(lengths) > 1 else 0
        score = 2.5 + min(0.5, length_variation / 500)  # 2.5 ~ 3.0

    # 长度奖励（长 prompt 通常意味着更深入的思考）
    if avg_length > 200:
        score = min(score + 0.3, 3.5)

    return _clamp_score(score)


def _calc_human_ai_judgment(events: list[dict]) -> float:
    """人机判断力：评估候选人对 AI 输出的批判性审查程度。

    指标:
    - AI_OUTPUT_EDIT 占 AI 响应总数的比例
    - 编辑深度（metadata.edit_depth）
    """
    ai_responses = [e for e in events if e.get("event_type") in ("AI_RESPONSE_RECV",)]
    ai_edits = [e for e in events if e.get("event_type") == "AI_OUTPUT_EDIT"]
    ai_accepts = [e for e in events if e.get("event_type") == "AI_OUTPUT_ACCEPT"]

    total_responses = len(ai_responses) + len(ai_edits) + len(ai_accepts)
    if total_responses == 0:
        return 1.0

    edit_ratio = len(ai_edits) / total_responses

    # 基础分
    if edit_ratio < 0.2:
        score = 1.0
    elif 0.2 <= edit_ratio < 0.4:
        score = 1.5 + (edit_ratio - 0.2) * 2.5  # 1.5 ~ 2.0
    elif 0.4 <= edit_ratio < 0.6:
        score = 2.5 + (edit_ratio - 0.4) * 2.5  # 2.5 ~ 3.0
    else:
        score = 3.0 + min(0.5, (edit_ratio - 0.6) * 1.25)  # 3.0 ~ 3.5

    # 编辑深度加成
    if ai_edits:
        avg_depth = statistics.mean(
            e.get("metadata", {}).get("edit_depth", 0) for e in ai_edits
        )
        if avg_depth > 0.5:
            score = min(score + 0.2, 3.5)

    return _clamp_score(score)


def _calc_architecture_design(events: list[dict]) -> float:
    """架构设计力：评估候选人在首个 prompt 中是否进行问题拆解与规划。

    指标:
    - 首个 AI_PROMPT_SEND 是否包含拆解/规划关键词
    """
    prompts = [e for e in events if e.get("event_type") == "AI_PROMPT_SEND"]
    if not prompts:
        return 1.0

    first_prompt_meta = prompts[0].get("metadata", {})
    first_prompt = first_prompt_meta.get("prompt_text", "")

    if not first_prompt:
        return 1.0

    # 统计拆解关键词出现次数
    kw_count = sum(1 for kw in DECOMPOSITION_KEYWORDS if kw in first_prompt)

    if kw_count == 0:
        score = 1.0  # 直接粘贴任务，无拆解
    elif kw_count == 1:
        score = 2.0  # 有一定结构
    elif kw_count == 2:
        score = 2.5
    else:
        score = 2.5 + min(0.5, (kw_count - 2) * 0.25)  # 2.5 ~ 3.0

    # 检查是否为纯复制粘贴（prompt 长度非常短）
    if len(first_prompt) < 20:
        score = min(score, 1.0)

    return _clamp_score(score)


def _calc_hybrid_orchestration(events: list[dict]) -> float:
    """混合编排力：评估候选人在手动编辑和 AI 辅助之间的编排能力。

    指标:
    - TEXT_INPUT / AI_PROMPT_SEND 比例
    - 交叉编排模式（手动 → AI → 手动 → AI）
    """
    text_inputs = [e for e in events if e.get("event_type") == "TEXT_INPUT"]
    ai_prompts = [e for e in events if e.get("event_type") == "AI_PROMPT_SEND"]

    total_actions = len(text_inputs) + len(ai_prompts)
    if total_actions == 0:
        return 1.0

    manual_ratio = len(text_inputs) / total_actions

    # 检查交叉编排模式：获取所有关键事件的时间线
    key_events = sorted(
        [e for e in events if e.get("event_type") in ("TEXT_INPUT", "AI_PROMPT_SEND")],
        key=lambda e: e.get("timestamp", ""),
    )

    # 统计模式切换次数
    interleave_count = 0
    prev_type = None
    for e in key_events:
        cur_type = e.get("event_type")
        if prev_type is not None and cur_type != prev_type:
            interleave_count += 1
        prev_type = cur_type

    # 基础分：基于手动编辑比例
    if manual_ratio < 0.1:
        score = 1.0  # 全 AI，无手动
    elif manual_ratio < 0.3:
        score = 1.5 + (manual_ratio - 0.1) * 2.5  # 1.5 ~ 2.0
    else:
        score = 2.5 + min(0.5, (manual_ratio - 0.3) * 1.0)  # 2.5 ~ 3.0

    # 交叉模式加分
    if interleave_count >= 3:
        score = min(score + 0.3, 3.5)

    return _clamp_score(score)


def _calc_cognitive_depth(events: list[dict]) -> float:
    """认知深度：评估候选人在 Stage 3 的事实核查能力与错误恢复行为。
    
    增强版：结合服务端心跳数据评估专注度和持续关注度。

    指标:
    - Stage 3 中是否有对 AI 输出的质疑行为
    - ERROR_ENCOUNTERED 数量和恢复情况
    - UNDO_REDO 次数（反映迭代与精炼）
    - 心跳间隔分析（服务端埋点，不可伪造）
    """
    # Stage 3 事件
    stage3_events = [e for e in events if e.get("stage") == 3]

    # Stage 3 中的编辑行为（暗示核查）
    stage3_edits = [
        e for e in stage3_events if e.get("event_type") == "AI_OUTPUT_EDIT"
    ]
    stage3_accepts = [
        e for e in stage3_events if e.get("event_type") == "AI_OUTPUT_ACCEPT"
    ]

    # 编辑深度
    edit_depths = [
        e.get("metadata", {}).get("edit_depth", 0) for e in stage3_edits
    ]
    deep_edits = sum(1 for d in edit_depths if d > 0.5)

    # Stage 3 中是否有 AI_PROMPT_SEND 包含质疑性关键词
    stage3_prompts = [
        e for e in stage3_events if e.get("event_type") == "AI_PROMPT_SEND"
    ]
    verification_keywords = ["验证", "检查", "确认", "数据", "来源", "准确", "真实", "核实", "查证"]
    verification_prompts = sum(
        1
        for p in stage3_prompts
        if any(kw in p.get("metadata", {}).get("prompt_text", "") for kw in verification_keywords)
    )

    # 错误处理
    all_errors = [e for e in events if e.get("event_type") == "ERROR_ENCOUNTERED"]
    stage3_errors = [e for e in stage3_events if e.get("event_type") == "ERROR_ENCOUNTERED"]
    recovered_errors = sum(
        1 for e in all_errors if e.get("metadata", {}).get("recovered", False)
    )

    # UNDO_REDO 次数
    undo_redos = [e for e in events if e.get("event_type") == "UNDO_REDO"]
    ur_count = len(undo_redos)

    # 心跳专注度分析（服务端埋点）
    heartbeats = [e for e in events if e.get("event_type") == "HEARTBEAT"]
    engagement_bonus = 0.0
    if len(heartbeats) >= 3:
        # 分析心跳间隔的规律性
        from datetime import datetime
        try:
            hb_times = []
            for hb in heartbeats:
                ts = hb.get("timestamp", "")
                if ts:
                    hb_times.append(datetime.fromisoformat(ts.replace("Z", "+00:00")))
            if len(hb_times) >= 3:
                hb_times.sort()
                intervals = [(hb_times[i+1] - hb_times[i]).total_seconds() for i in range(len(hb_times)-1)]
                avg_interval = statistics.mean(intervals)
                # 规律心跳（60-120s 间隔）= 专注
                if 30 < avg_interval < 180:
                    engagement_bonus = 0.2
                # 非常规律 + 长时间 = 高度专注
                if 30 < avg_interval < 180 and len(heartbeats) > 10:
                    engagement_bonus = 0.3
        except Exception:
            pass

    # 计分
    score = 1.0

    # 事实核查行为加分
    if verification_prompts > 0:
        score = max(score, 2.0)
    if deep_edits > 0:
        score = max(score, 2.5)
    if verification_prompts > 0 and deep_edits > 0:
        score = max(score, 2.8)
    if verification_prompts >= 2 and deep_edits >= 1:
        score = max(score, 3.0)

    # 错误恢复加分
    if len(all_errors) > 0 and recovered_errors > 0:
        score = min(score + 0.2, 4.0)
    if recovered_errors >= 2:
        score = min(score + 0.2, 4.0)

    # 迭代精炼加分（UNDO_REDO）
    if ur_count >= 3:
        score = min(score + 0.3, 4.0)
    elif ur_count >= 1:
        score = min(score + 0.1, 4.0)

    # 专注度加分（心跳数据）
    score = min(score + engagement_bonus, 4.0)

    return _clamp_score(score)


def _calc_problem_modeling(events: list[dict]) -> float:
    """问题建模能力：评估候选人首次行动是否先分析再行动。

    指标:
    - 首个事件类型（TASK_START 之后第一个关键事件）
    - 首个 prompt 是否重新表述问题而非简单复制
    """
    key_types = (
        "AI_PROMPT_SEND",
        "TEXT_INPUT",
        "COPY_PASTE",
        "TASK_SUBMIT",
    )

    # 找到 TASK_START 之后的第一个关键事件
    task_started = False
    first_key_event = None
    for e in events:
        et = e.get("event_type", "")
        if et == "TASK_START":
            task_started = True
            continue
        if task_started and et in key_types:
            first_key_event = e
            break

    if first_key_event is None:
        # 没有找到 TASK_START 后的关键事件，使用第一个关键事件
        for e in events:
            if e.get("event_type", "") in key_types:
                first_key_event = e
                break

    if first_key_event is None:
        return 1.0

    first_type = first_key_event.get("event_type", "")

    # 首个事件就是 TASK_SUBMIT（直接提交，无任何分析）→ 最低分
    if first_type == "TASK_SUBMIT":
        return 1.0

    # 首个事件是 COPY_PASTE（直接粘贴任务）→ 低分
    if first_type == "COPY_PASTE":
        return 1.0

    # 首个事件是 TEXT_INPUT（先手动开始，有一定分析意识）
    if first_type == "TEXT_INPUT":
        text_len = first_key_event.get("metadata", {}).get("text_length", 0)
        if text_len > 50:
            return 2.0  # 有实质性的手动分析
        return 1.5

    # 首个事件是 AI_PROMPT_SEND
    first_prompt = first_key_event.get("metadata", {}).get("prompt_text", "")

    if not first_prompt:
        return 1.0

    # 检查是否包含拆解/重构关键词（在长度检查之前，中文 prompt 可能短但质量高）
    kw_count = sum(1 for kw in DECOMPOSITION_KEYWORDS if kw in first_prompt)
    clarification_count = sum(1 for kw in CLARIFICATION_KEYWORDS if kw in first_prompt)

    # 检查 prompt 长度（太短且无拆解关键词 → 可能是直接粘贴任务描述）
    if len(first_prompt) < 30 and kw_count == 0 and clarification_count == 0:
        return 1.0  # 直接复制粘贴

    if kw_count == 0 and clarification_count == 0:
        score = 1.5  # 有一些表述但无明显拆解
    elif kw_count >= 1 and clarification_count >= 1:
        score = 2.5 + min(0.5, kw_count * 0.1)  # 拆解 + 澄清 → 2.5 ~ 3.0
    elif kw_count >= 2:
        score = 2.5 + min(0.5, kw_count * 0.2)  # 明显拆解 → 2.5 ~ 3.0
    elif kw_count == 1:
        score = 2.0  # 有一些结构
    else:
        score = 2.0  # 有澄清性问题但无拆解

    return _clamp_score(score)


# ============================================================================
# 3. 等级判定
# ============================================================================


# ============================================================================
# 评分权重配置
# ============================================================================

# 旧六维度权重（基于维度对 AI 协同能力的重要性分配）
DIMENSION_WEIGHTS = {
    "ai_fluency": 0.15,         # AI 流利度：基础能力，权重适中
    "human_ai_judgment": 0.25,  # 人机判断力：核心能力，权重最高
    "architecture_design": 0.20, # 架构设计力：高阶能力，权重较高
    "hybrid_orchestration": 0.15, # 混合编排力：实践能力，权重适中
    "cognitive_depth": 0.15,    # 认知深度：潜力指标，权重适中
    "problem_modeling": 0.10,   # 问题建模：可从其他维度侧面反映
}


def _determine_level_original(average_score: float) -> str:
    """原始硬编码阈值版本（保留作为 fallback）"""
    if average_score < 1.8:
        return "L1"
    elif average_score < 2.5:
        return "L2"
    elif average_score < 3.2:
        return "L3"
    else:
        return "L4"


# ============================================================================
# 内部辅助函数
# ============================================================================


def _clamp_score(score: float, min_val: float = 1.0, max_val: float = 4.0) -> float:
    """限制得分在 [min_val, max_val] 范围内，保留一位小数。

    注意：max_val 从 3.5 上调到 4.0，以区分"专家"级别的候选人。
    L4 候选人应当在多个维度达到 3.5+ 的水平。

    参数:
        score: 原始得分
        min_val: 最小值，默认 1.0
        max_val: 最大值，默认 4.0

    返回:
        限制后的得分
    """
    return round(max(min_val, min(max_val, score)), 1)


# ============================================================================
# 新六维度评分框架（高管测评）
# ============================================================================

def calculate_new_dimension_scores(
    events: list[dict], interactions: list[dict]
) -> dict[str, float]:
    """基于行为事件和 AI 交互计算新六维度评分（0-100分）。

    六个维度:
        problem_definition: 问题定义能力
        task_decomposition: 任务拆解能力
        information_acquisition: 信息获取能力
        hypothesis_construction: 假设构建能力
        hypothesis_correction: 假设修正能力
        integrated_judgment: 综合判断力

    参数:
        events: 行为事件列表
        interactions: AI 交互记录列表

    返回:
        包含六个维度得分的字典
    """
    parsed_events = _ensure_parsed_metadata(events)
    
    scores: dict[str, float] = {}
    
    scores["problem_definition"] = _calc_problem_definition(parsed_events, interactions)
    scores["task_decomposition"] = _calc_task_decomposition_new(parsed_events, interactions)
    scores["information_acquisition"] = _calc_information_acquisition(parsed_events, interactions)
    scores["hypothesis_construction"] = _calc_hypothesis_construction(parsed_events, interactions)
    scores["hypothesis_correction"] = _calc_hypothesis_correction(parsed_events, interactions)
    scores["integrated_judgment"] = _calc_integrated_judgment(parsed_events, interactions)
    
    return scores


def _calc_problem_definition(events: list[dict], interactions: list[dict]) -> float:
    """问题定义能力：在模糊和矛盾信息中界定核心问题的能力。"""
    score = 50.0  # 基础分
    
    # 获取所有 prompt
    prompts = [
        e.get("metadata", {}).get("prompt_text", "") 
        for e in events 
        if e.get("event_type") == "AI_PROMPT_SEND"
    ]
    prompts = [p for p in prompts if p]
    
    if not prompts:
        return max(30.0, score)
    
    # 1. 检查是否包含问题界定关键词
    problem_keywords = ["核心问题", "主要矛盾", "问题本质", "关键在于", "根本原因", "核心在于"]
    has_problem_definition = any(
        any(kw in p for kw in problem_keywords) 
        for p in prompts
    )
    if has_problem_definition:
        score += 20.0
    
    # 2. 检查是否对矛盾信息敏感
    contradiction_keywords = ["矛盾", "冲突", "不一致", "有问题", "不对", "需要核实"]
    has_contradiction_awareness = any(
        any(kw in p for kw in contradiction_keywords) 
        for p in prompts
    )
    if has_contradiction_awareness:
        score += 15.0
    
    # 3. 检查首个 prompt 是否不是简单复述任务
    first_prompt = prompts[0] if prompts else ""
    if len(first_prompt) > 100 and first_prompt.strip():
        score += 15.0
    
    return min(100.0, max(0.0, score))


def _calc_task_decomposition_new(events: list[dict], interactions: list[dict]) -> float:
    """任务拆解能力：将复杂问题拆解为可执行子任务的能力。"""
    score = 40.0  # 基础分
    
    # 获取所有 prompt
    prompts = [
        e.get("metadata", {}).get("prompt_text", "") 
        for e in events 
        if e.get("event_type") == "AI_PROMPT_SEND"
    ]
    prompts = [p for p in prompts if p]
    
    if not prompts:
        return max(20.0, score)
    
    # 1. 检查拆解关键词
    decomposition_keywords = [
        "第一步", "第二步", "第三步", "首先", "其次", "最后",
        "1.", "2.", "3.", "阶段一", "阶段二", "阶段三",
        "拆解为", "分解为", "分步骤", "分阶段"
    ]
    decomposition_count = sum(
        1 for p in prompts 
        if any(kw in p for kw in decomposition_keywords)
    )
    if decomposition_count >= 2:
        score += 25.0
    elif decomposition_count >= 1:
        score += 15.0
    
    # 2. 检查是否有多轮分步骤调用
    ai_prompts = [e for e in events if e.get("event_type") == "AI_PROMPT_SEND"]
    if len(ai_prompts) >= 4:
        score += 20.0
    elif len(ai_prompts) >= 2:
        score += 10.0
    
    # 3. 检查子任务之间的独立性
    # 简单规则：如果 prompt 长度变化较大，说明在处理不同子任务
    if len(prompts) >= 2:
        lengths = [len(p) for p in prompts]
        avg_length = sum(lengths) / len(lengths)
        variance = sum((l - avg_length) ** 2 for l in lengths) / len(lengths)
        if variance > 5000:  # 长度变化大
            score += 15.0
    
    return min(100.0, max(0.0, score))


def _calc_information_acquisition(events: list[dict], interactions: list[dict]) -> float:
    """信息获取能力：主动搜集数据、追问细节、交叉验证的能力。"""
    score = 40.0  # 基础分
    
    # 1. 检查追问行为（多轮对话）
    ai_prompts = [e for e in events if e.get("event_type") == "AI_PROMPT_SEND"]
    follow_up_count = 0
    for i in range(1, len(ai_prompts)):
        prev_meta = ai_prompts[i-1].get("metadata", {})
        curr_meta = ai_prompts[i].get("metadata", {})
        # 检查是否是追问（迭代标记）
        if curr_meta.get("iteration") and curr_meta.get("iteration") > 1:
            follow_up_count += 1
    
    if follow_up_count >= 3:
        score += 25.0
    elif follow_up_count >= 1:
        score += 15.0
    
    # 2. 检查是否有验证关键词
    verification_keywords = [
        "核实", "验证", "确认", "交叉检查", "数据来源",
        "准确吗", "对吗", "是吗", "真的吗"
    ]
    prompts = [
        e.get("metadata", {}).get("prompt_text", "") 
        for e in events 
        if e.get("event_type") == "AI_PROMPT_SEND"
    ]
    has_verification = any(
        any(kw in p for kw in verification_keywords) 
        for p in prompts if p
    )
    if has_verification:
        score += 20.0
    
    # 3. 检查 Stage 3 中的事实核查行为
    stage3_events = [e for e in events if e.get("stage") == 3]
    if stage3_events:
        score += 15.0
    
    return min(100.0, max(0.0, score))


def _calc_hypothesis_construction(events: list[dict], interactions: list[dict]) -> float:
    """假设构建能力：在信息不完整时提出可验证假设的能力。"""
    score = 35.0  # 基础分
    
    prompts = [
        e.get("metadata", {}).get("prompt_text", "") 
        for e in events 
        if e.get("event_type") == "AI_PROMPT_SEND"
    ]
    prompts = [p for p in prompts if p]
    
    if not prompts:
        return max(20.0, score)
    
    # 1. 检查假设相关关键词
    hypothesis_keywords = [
        "可能是", "推测", "假设", "如果", "假定", "猜想",
        "初步判断", "倾向于认为", "有可能", "会不会是"
    ]
    hypothesis_count = sum(
        1 for p in prompts 
        if any(kw in p for kw in hypothesis_keywords)
    )
    
    if hypothesis_count >= 3:
        score += 30.0
    elif hypothesis_count >= 1:
        score += 20.0
    
    # 2. 检查是否有多个假设
    multiple_hypothesis_keywords = ["两种可能", "几种可能性", "可能一", "可能二", "一方面", "另一方面"]
    has_multiple = any(
        any(kw in p for kw in multiple_hypothesis_keywords) 
        for p in prompts
    )
    if has_multiple:
        score += 20.0
    
    # 3. 检查是否有可验证的判断标准
    verification_criteria_keywords = ["如果", "只要", "当", "验证方法", "判断标准"]
    has_criteria = any(
        any(kw in p for kw in verification_criteria_keywords) 
        for p in prompts
    )
    if has_criteria:
        score += 15.0
    
    return min(100.0, max(0.0, score))


def _calc_hypothesis_correction(events: list[dict], interactions: list[dict]) -> float:
    """假设修正能力：在新证据出现时主动修正或推翻先前假设的能力。"""
    score = 40.0  # 基础分
    
    # 1. 检查 UNDO/REDO 行为（表明在调整思路）
    undo_count = sum(
        1 for e in events 
        if e.get("event_type") == "UNDO_REDO"
    )
    if undo_count >= 3:
        score += 20.0
    elif undo_count >= 1:
        score += 10.0
    
    # 2. 检查修正相关关键词
    correction_keywords = [
        "更正", "修正", "调整", "之前的想法", "重新考虑",
        "推翻", "之前不对", "我错了", "看来不是"
    ]
    prompts = [
        e.get("metadata", {}).get("prompt_text", "") 
        for e in events 
        if e.get("event_type") == "AI_PROMPT_SEND"
    ]
    has_correction = any(
        any(kw in p for kw in correction_keywords) 
        for p in prompts if p
    )
    if has_correction:
        score += 25.0
    
    # 3. 检查是否有 AI_OUTPUT_EDIT（表明在调整输出）
    edit_count = sum(
        1 for e in events 
        if e.get("event_type") == "AI_OUTPUT_EDIT"
    )
    if edit_count >= 2:
        score += 15.0
    elif edit_count >= 1:
        score += 8.0
    
    return min(100.0, max(0.0, score))


def _calc_integrated_judgment(events: list[dict], interactions: list[dict]) -> float:
    """综合判断力：在多方信息、利益冲突和不确定性中做出合理决策的能力。"""
    score = 35.0  # 基础分
    
    prompts = [
        e.get("metadata", {}).get("prompt_text", "") 
        for e in events 
        if e.get("event_type") == "AI_PROMPT_SEND"
    ]
    prompts = [p for p in prompts if p]
    
    if not prompts:
        return max(20.0, score)
    
    # 1. 检查权衡关键词
    tradeoff_keywords = [
        "权衡", "平衡", "利弊", "优缺点", "风险", "收益",
        "一方面", "另一方面", "虽然", "但是", "然而"
    ]
    tradeoff_count = sum(
        1 for p in prompts 
        if any(kw in p for kw in tradeoff_keywords)
    )
    if tradeoff_count >= 2:
        score += 25.0
    elif tradeoff_count >= 1:
        score += 15.0
    
    # 2. 检查是否考虑多方利益
    stakeholder_keywords = [
        " CEO ", " CFO ", " 团队", " 客户", " 供应商",
        " 股东", " 员工", " 管理层", "利益相关方"
    ]
    has_stakeholder = any(
        any(kw in p for kw in stakeholder_keywords) 
        for p in prompts
    )
    if has_stakeholder:
        score += 20.0
    
    # 3. 检查是否有明确的决策理由
    reasoning_keywords = [
        "因为", "所以", "因此", "基于", "考虑到", "鉴于",
        "理由是", "原因在于", "判断依据"
    ]
    has_reasoning = any(
        any(kw in p for kw in reasoning_keywords) 
        for p in prompts
    )
    if has_reasoning:
        score += 20.0
    
    return min(100.0, max(0.0, score))


def _ensure_parsed_metadata(events: list[dict]) -> list[dict]:
    """确保事件列表中的 metadata 字段是 dict 类型。

    数据库可能存储 JSON 字符串或已解析的 dict。

    参数:
        events: 原始事件列表

    返回:
        metadata 已解析为 dict 的事件列表
    """
    import json

    result = []
    for e in events:
        evt = dict(e)
        meta = evt.get("metadata", {})
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except (json.JSONDecodeError, TypeError):
                meta = {}
        evt["metadata"] = meta
        result.append(evt)
    return result


def _fmt_ts(ts: str) -> str:
    """格式化 ISO 时间戳为可读形式。

    参数:
        ts: ISO 8601 格式时间戳

    返回:
        格式化的时间字符串，如 "14:30:15"
    """
    if not ts:
        return "--:--:--"
    try:
        # 尝试解析 ISO 8601 格式
        if "T" in ts:
            return ts.split("T")[1].split(".")[0][:8]
        # 已是简洁格式
        return ts[:8] if len(ts) >= 8 else ts
    except (IndexError, ValueError):
        return ts[:8] if len(ts) >= 8 else ts


def _relative_time(ts: str, ref_ts: Optional[str]) -> str:
    """计算相对于参考时间戳的 [MM:SS] 格式时间。

    参数:
        ts: 当前事件的时间戳
        ref_ts: 参考时间戳（通常为该阶段第一个事件的时间）

    返回:
        [MM:SS] 格式的相对时间
    """
    if not ts or not ref_ts:
        return "--:--"
    try:
        # 解析 ISO 时间
        if "T" in ts:
            t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            r = datetime.fromisoformat(ref_ts.replace("Z", "+00:00"))
        else:
            t = datetime.fromisoformat(ts)
            r = datetime.fromisoformat(ref_ts)
        diff = (t - r).total_seconds()
        minutes = int(diff // 60)
        seconds = int(diff % 60)
        return f"{minutes:02d}:{seconds:02d}"
    except (ValueError, TypeError):
        return "--:--"


def _ref_ts(stage_events: list[dict]) -> Optional[str]:
    """获取阶段中第一个事件的 timestamp 作为参考时间。

    参数:
        stage_events: 阶段事件列表

    返回:
        参考时间戳或 None
    """
    for e in stage_events:
        ts = e.get("timestamp", "")
        if ts:
            return ts
    return None


# ============================================================================
# 热更新钩子（由 ConfigService 调用）
# ============================================================================

# 运行时阈值配置（初始化为代码默认值，可被 ConfigService 热更新）
_RUNTIME_THRESHOLDS = {
    "L1": 1.8,
    "L2": 2.5,
    "L3": 3.2,
}

_RUNTIME_SCORE_RANGE = {
    "min": 1.0,
    "max": 4.0,
}


def update_evaluation_config(key: str, value: Any):
    """热更新评估配置（由 ConfigService 调用）

    支持更新的配置项：
    - dimension_weights: 维度权重字典
    - level_thresholds: 级别阈值字典
    - score_range: 评分范围字典
    - keywords: 关键词字典
    """
    global DIMENSION_WEIGHTS, DECOMPOSITION_KEYWORDS, CLARIFICATION_KEYWORDS
    global VERIFICATION_KEYWORDS, _RUNTIME_THRESHOLDS, _RUNTIME_SCORE_RANGE

    if key == "dimension_weights":
        DIMENSION_WEIGHTS = value
    elif key == "level_thresholds":
        _RUNTIME_THRESHOLDS = value
    elif key == "score_range":
        _RUNTIME_SCORE_RANGE = value
    elif key == "keywords":
        if isinstance(value, dict):
            if "decomposition" in value:
                DECOMPOSITION_KEYWORDS = value["decomposition"]
            if "clarification" in value:
                CLARIFICATION_KEYWORDS = value["clarification"]
            if "verification" in value:
                VERIFICATION_KEYWORDS = value["verification"]

# 修改 determine_level 和 _clamp_score 使用运行时配置（已在文件末尾重新定义）


def determine_level(average_score: float) -> str:
    """根据加权平均得分判定能力等级（使用运行时可配置阈值）"""
    t = _RUNTIME_THRESHOLDS
    if average_score < t.get("L1", 1.8):
        return "L1"
    elif average_score < t.get("L2", 2.5):
        return "L2"
    elif average_score < t.get("L3", 3.2):
        return "L3"
    else:
        return "L4"


def _clamp_score(score: float, min_val: float = None, max_val: float = None) -> float:
    """限制得分在可配置范围内，保留一位小数"""
    r = _RUNTIME_SCORE_RANGE
    min_val = min_val if min_val is not None else r.get("min", 1.0)
    max_val = max_val if max_val is not None else r.get("max", 4.0)
    return round(max(min_val, min(score, max_val)), 1)
