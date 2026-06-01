"""
AI 沙盒行为洞察系统 - 评估引擎
==================================
负责矛盾检测（Contradiction Detection）、认知画像生成（Cognitive Profile）和置信度评估。

矛盾检测对齐 ai-talent-grader skill 中的六类行为信号检测逻辑，
通过事件流与 AI 交互记录交叉分析，产出结构化矛盾信号。
"""

import sys
from pathlib import Path

# 将 server 根目录加入路径，以便导入 models
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models import Contradiction


# ============================================================================
# 常量定义
# ============================================================================

# 行为轨迹异常光滑检测阈值
SMOOTH_OVER_LABEL = "行为轨迹异常光滑"
SMOOTH_OVER_DESC = "全程无撤销、无错误、无修改AI输出"

# 决策模糊检测阈值
DECISION_AMBIGUITY_LABEL = "对需求变更反应迟缓"
DECISION_AMBIGUITY_DESC = "Stage 2 突发事件后未及时调整策略"
DECISION_MIN_PROMPTS_STAGE2 = 1       # Stage 2 至少应有的 AI 提示次数
DECISION_MAX_DELAY_SECONDS = 120      # Stage 2 切换后最大延迟（秒）

# 数据矛盾检测
DATA_CONTRADICTION_LABEL = "事实核查能力未触发"
DATA_CONTRADICTION_DESC = "Stage 3 中AI输出的异常数据未被质疑"

# 复制粘贴检测阈值
COPY_PASTE_LABEL = "大量复制粘贴行为"
COPY_PASTE_DESC = "可能缺乏独立思考"
COPY_PASTE_MIN_COUNT = 5
COPY_PASTE_RATIO_THRESHOLD = 0.15

# 浅层编辑检测
SHALLOW_EDIT_LABEL = "AI输出修改仅停留在措辞层面"
SHALLOW_EDIT_DESC = "未见逻辑层或结构层调整"

# 无拆解检测阈值
NO_DECOMP_LABEL = "任务开始即向AI发送完整需求"
NO_DECOMP_DESC = "未进行问题拆解或需求澄清"
NO_DECOMP_MAX_DELAY_SECONDS = 30
NO_DECOMP_LENGTH_RATIO = 0.8


# ============================================================================
# 辅助函数
# ============================================================================

def _safe_find_events_by_type(events: list[dict], event_type: str) -> list[dict]:
    """安全查找指定类型的事件，处理 events 为 None 或空列表的情况。"""
    if not events:
        return []
    return [e for e in events if e.get("event_type") == event_type]


def _safe_count_events_by_type(events: list[dict], event_type: str) -> int:
    """安全统计指定类型的事件数量。"""
    return len(_safe_find_events_by_type(events, event_type))


def _safe_find_events_by_stage(events: list[dict], stage: int) -> list[dict]:
    """安全查找指定阶段的事件。"""
    if not events:
        return []
    return [e for e in events if e.get("stage") == stage]


def _safe_get_first(events: list[dict], event_type: str, stage: int = None):
    """安全获取第一个满足条件的事件。"""
    if not events:
        return None
    for e in events:
        matches_type = e.get("event_type") == event_type
        matches_stage = stage is None or e.get("stage") == stage
        if matches_type and matches_stage:
            return e
    return None


def _parse_timestamp(ts_str: str) -> float:
    """将 ISO 8601 时间字符串转换为 Unix 时间戳（秒），失败返回 -1。"""
    from datetime import datetime
    try:
        # 处理带时区的 ISO 8601 格式
        dt = datetime.fromisoformat(ts_str)
        return dt.timestamp()
    except (ValueError, TypeError):
        return -1.0


def _count_event_type_values(
    events: list[dict], event_type: str, field_path: str, target_values: set
) -> int:
    """
    统计指定事件类型中，metadata 内某个字段取值在目标集合中的事件个数。
    field_path 形如 "metadata.edit_type" 或 "metadata.xxx"。
    """
    if not events or not field_path:
        return 0
    parts = field_path.split(".")
    count = 0
    for e in events:
        if e.get("event_type") != event_type:
            continue
        value = e
        for part in parts:
            value = value.get(part) if isinstance(value, dict) else None
            if value is None:
                break
        if value in target_values:
            count += 1
    return count


# ============================================================================
# 六大矛盾检测
# ============================================================================

def detect_contradictions(events: list[dict], interactions: list[dict]) -> list[Contradiction]:
    """
    从行为日志中检测六类矛盾信号，对齐 ai-talent-grader skill 的检测逻辑。

    Args:
        events: 行为事件列表，每项包含 event_type / stage / timestamp / metadata 等字段
        interactions: AI 交互记录列表，每项包含 stage / prompt / response /
                      contains_hallucination 等字段

    Returns:
        Contradiction 对象列表
    """
    contradictions = []

    # ---- 1. "过度光滑"检测 ----
    # 全程无 UNDO_REDO、无 ERROR_ENCOUNTERED、无 AI_OUTPUT_EDIT
    undo_count = _safe_count_events_by_type(events, "UNDO_REDO")
    error_count = _safe_count_events_by_type(events, "ERROR_ENCOUNTERED")
    edit_count = _safe_count_events_by_type(events, "AI_OUTPUT_EDIT")

    if undo_count == 0 and error_count == 0 and edit_count == 0:
        contradictions.append(Contradiction(
            type=SMOOTH_OVER_LABEL,
            description=SMOOTH_OVER_DESC,
            confidence="high",
            evidence=f"UNDO_REDO={undo_count}, ERROR_ENCOUNTERED={error_count}, AI_OUTPUT_EDIT={edit_count}"
        ))

    # ---- 2. "决策模糊"检测 ----
    # Stage 2 中极少 AI_PROMPT_SEND，或从 STAGE_TRANSITION(2) 到首次 AI_PROMPT_SEND 时间过长
    stage2_events = _safe_find_events_by_stage(events, 2)
    stage2_prompts = _safe_find_events_by_type(stage2_events, "AI_PROMPT_SEND")

    is_decision_ambiguous = False

    if len(stage2_prompts) <= DECISION_MIN_PROMPTS_STAGE2:
        is_decision_ambiguous = True

    # 检测延迟：找到 Stage 2 的 STAGE_TRANSITION 和第一个 AI_PROMPT_SEND 的时间差
    stage2_transition = _safe_get_first(events, "STAGE_TRANSITION", stage=2)
    stage2_first_prompt = _safe_get_first(events, "AI_PROMPT_SEND", stage=2)

    if stage2_transition and stage2_first_prompt:
        trans_ts = _parse_timestamp(stage2_transition.get("timestamp", ""))
        prompt_ts = _parse_timestamp(stage2_first_prompt.get("timestamp", ""))
        if trans_ts > 0 and prompt_ts > 0:
            delay = prompt_ts - trans_ts
            if delay > DECISION_MAX_DELAY_SECONDS:
                is_decision_ambiguous = True

    if is_decision_ambiguous:
        evidence_parts = [f"Stage2 AI_PROMPT_SEND数量={len(stage2_prompts)}"]
        if stage2_transition and stage2_first_prompt:
            trans_ts = _parse_timestamp(stage2_transition.get("timestamp", ""))
            prompt_ts = _parse_timestamp(stage2_first_prompt.get("timestamp", ""))
            if trans_ts > 0 and prompt_ts > 0:
                evidence_parts.append(f"进入Stage2后首次AI交互延迟={prompt_ts - trans_ts:.0f}秒")
        contradictions.append(Contradiction(
            type=DECISION_AMBIGUITY_LABEL,
            description=DECISION_AMBIGUITY_DESC,
            confidence="medium",
            evidence="; ".join(evidence_parts)
        ))

    # ---- 3. "数据矛盾"检测 ----
    # Stage 3: 存在幻觉数据但无后续质疑
    stage3_interactions = [i for i in interactions if i.get("stage") == 3] if interactions else []
    hallucination_interactions = [
        i for i in stage3_interactions if i.get("contains_hallucination") is True
    ]

    if hallucination_interactions:
        # 检查是否有后续 AI_PROMPT_SEND 来质疑/核实数据
        # 判断标准：幻觉交互之后是否存在新的 AI_PROMPT_SEND
        # 为简化起见，若 Stage 3 总 AI_PROMPT_SEND 仅等于幻觉所在交互的轮次，
        # 即说明没有额外质疑
        stage3_prompts = _safe_find_events_by_type(
            _safe_find_events_by_stage(events, 3), "AI_PROMPT_SEND"
        )
        # 交互记录中的 promt 发送次数也应与事件中的 AI_PROMPT_SEND 对应
        # 这里以 contains_hallucination 的出现位置判断
        hallucination_positions = [
            idx for idx, i in enumerate(stage3_interactions)
            if i.get("contains_hallucination") is True
        ]

        all_stage3_interactions = len(stage3_interactions)

        # 如果最后一条交互包含幻觉且这是最后一条交互 -> 未被质疑
        # 或者存在幻觉但无后续 prompt（事件中 AI_PROMPT_SEND <= 幻觉发生次数）
        prompt_count_stage3 = len(stage3_prompts)
        if all_stage3_interactions > 0:
            # 幻觉发生后若无新 prompt，则未被质疑
            last_hallucination_idx = max(hallucination_positions) if hallucination_positions else -1
            # 幻觉不是最后一条记录，说明可能已被后续交互覆盖—但还需判断后续是否是质疑
            # 简化：若总 prompt 数 <= 幻觉交互数，说明无额外质疑
            if prompt_count_stage3 <= len(hallucination_interactions):
                contradictions.append(Contradiction(
                    type=DATA_CONTRADICTION_LABEL,
                    description=DATA_CONTRADICTION_DESC,
                    confidence="high",
                    evidence=(
                        f"Stage3幻觉交互={len(hallucination_interactions)}次, "
                        f"后续质疑交互=0次"
                    )
                ))

    # ---- 4. "复制粘贴"检测 ----
    copy_count = _safe_count_events_by_type(events, "COPY_PASTE")
    total_events = len(events) if events else 0

    if copy_count > COPY_PASTE_MIN_COUNT and total_events > 0:
        ratio = copy_count / total_events
        if ratio > COPY_PASTE_RATIO_THRESHOLD:
            contradictions.append(Contradiction(
                type=COPY_PASTE_LABEL,
                description=COPY_PASTE_DESC,
                confidence="medium",
                evidence=f"COPY_PASTE次数={copy_count}, 占比={ratio:.1%}"
            ))

    # ---- 5. "浅层编辑"检测 ----
    edit_events = _safe_find_events_by_type(events, "AI_OUTPUT_EDIT")
    if edit_events:
        deep_edit_keywords = {"logic", "structure"}
        edit_types_found = set()
        for e in edit_events:
            metadata = e.get("metadata", {}) or {}
            edit_type = metadata.get("edit_type", "")
            edit_types_found.add(edit_type)

        # 如果所有编辑 type 都不是 logic 或 structure，只有 wording
        has_deep_edit = bool(edit_types_found & deep_edit_keywords)
        has_only_wording = edit_types_found == {"wording"} or (
            not has_deep_edit and "wording" in edit_types_found
        )

        if has_only_wording or (not has_deep_edit and len(edit_types_found) > 0):
            contradictions.append(Contradiction(
                type=SHALLOW_EDIT_LABEL,
                description=SHALLOW_EDIT_DESC,
                confidence="medium",
                evidence=f"AI_OUTPUT_EDIT edit_type分布={edit_types_found}"
            ))

    # ---- 6. "无拆解"检测 ----
    stage1_events = _safe_find_events_by_stage(events, 1)
    task_start = _safe_get_first(stage1_events, "TASK_START")
    first_stage1_prompt = _safe_get_first(stage1_events, "AI_PROMPT_SEND")

    if task_start and first_stage1_prompt:
        start_ts = _parse_timestamp(task_start.get("timestamp", ""))
        prompt_ts = _parse_timestamp(first_stage1_prompt.get("timestamp", ""))

        if start_ts > 0 and prompt_ts > 0:
            delay = prompt_ts - start_ts
            if delay <= NO_DECOMP_MAX_DELAY_SECONDS:
                # 进一步检查 prompt 长度是否接近任务描述长度（疑似直接复制粘贴需求）
                prompt_length = first_stage1_prompt.get("metadata", {}).get(
                    "prompt_length", 0
                )
                # 如果 metadata 中有 task_description_length 则可计算比例
                # 此处兼容两种数据源
                task_desc_len = first_stage1_prompt.get("metadata", {}).get(
                    "task_description_length", 0
                )
                if task_desc_len > 0 and prompt_length > 0:
                    if prompt_length > task_desc_len * NO_DECOMP_LENGTH_RATIO:
                        contradictions.append(Contradiction(
                            type=NO_DECOMP_LABEL,
                            description=NO_DECOMP_DESC,
                            confidence="medium",
                            evidence=(
                                f"TASK_START-首次AI_PROMPT_SEND间隔={delay:.0f}秒, "
                                f"首次prompt长度/任务描述长度={prompt_length / task_desc_len:.1%}"
                            )
                        ))
                else:
                    # 如果拿不到长度比率，仅凭时间判断
                    contradictions.append(Contradiction(
                        type=NO_DECOMP_LABEL,
                        description=NO_DECOMP_DESC,
                        confidence="medium",
                        evidence=(
                            f"TASK_START-首次AI_PROMPT_SEND间隔={delay:.0f}秒"
                        )
                    ))

    return contradictions


# ============================================================================
# 认知画像生成
# ============================================================================

def generate_cognitive_profile(
    events: list[dict], interactions: list[dict], scores: dict
) -> dict:
    """
    基于行为模式生成八维度认知画像（认知画像）。

    Args:
        events: 行为事件列表
        interactions: AI 交互记录列表
        scores: 六维度评分 {"ai_fluency": 3.5, "human_ai_judgment": 2.8, ...}

    Returns:
        包含八个维度评语的字典
    """
    profile = {
        "decision_style": "",
        "thinking_structure": "",
        "ai_collaboration_habit": "",
        "complexity_capacity": "",
        "ownership": "",
        "risk_preference": "",
        "correction_ability": "",
        "authenticity_risk": "",
    }

    if not events:
        # 无数据时的默认画像
        profile["decision_style"] = "未知 - 无行为数据"
        profile["thinking_structure"] = "未知 - 无行为数据"
        profile["ai_collaboration_habit"] = "未知 - 无行为数据"
        profile["complexity_capacity"] = "未知 - 无行为数据"
        profile["ownership"] = "未知 - 无行为数据"
        profile["risk_preference"] = "未知 - 无行为数据"
        profile["correction_ability"] = "未知 - 无行为数据"
        profile["authenticity_risk"] = "未知 - 无行为数据"
        return profile

    # ---- decision_style: 决策风格 ----
    # 基于 Stage 1 的首个 AI_PROMPT_SEND 行为判断
    stage1_prompts = _safe_find_events_by_type(
        _safe_find_events_by_stage(events, 1), "AI_PROMPT_SEND"
    )
    task_start = _safe_get_first(events, "TASK_START")

    if stage1_prompts:
        first_prompt = stage1_prompts[0]
        prompt_meta = first_prompt.get("metadata", {}) or {}

        # 拆解信号：metadata 中有 decomposition_steps 或 prompt 包含结构化标记
        is_decomposed = prompt_meta.get("is_decomposed", False)
        if not is_decomposed:
            # 降级检测：prompt 内容的行数较多通常意味着拆解
            prompt_text = prompt_meta.get("prompt_text", "") or prompt_meta.get("message", "")
            is_decomposed = isinstance(prompt_text, str) and prompt_text.count("\n") >= 3

        if is_decomposed:
            profile["decision_style"] = "分析型 - 先拆解后执行"
        elif task_start:
            # 判断是否为直接复制粘贴任务描述
            start_ts = _parse_timestamp(task_start.get("timestamp", ""))
            prompt_ts = _parse_timestamp(first_prompt.get("timestamp", ""))
            if start_ts > 0 and prompt_ts > 0 and (prompt_ts - start_ts) <= NO_DECOMP_MAX_DELAY_SECONDS:
                profile["decision_style"] = "执行型 - 接到任务立即动手"
            else:
                profile["decision_style"] = "执行型 - 接到任务立即动手"
        else:
            profile["decision_style"] = "执行型 - 接到任务立即动手"

        # 若有多轮对话，倾向于迭代型
        total_prompts = _safe_count_events_by_type(events, "AI_PROMPT_SEND")
        if total_prompts >= 5 and not is_decomposed:
            profile["decision_style"] = "迭代型 - 通过多轮对话逐步逼近"
    else:
        profile["decision_style"] = "执行型 - 无AI交互记录"

    # ---- thinking_structure: 思维结构 ----
    # 基于 prompt 长度序列判断
    all_prompts = _safe_find_events_by_type(events, "AI_PROMPT_SEND")
    if len(all_prompts) >= 2:
        prompt_lengths = []
        for p in all_prompts:
            meta = p.get("metadata", {}) or {}
            pl = meta.get("prompt_length", 0)
            if pl > 0:
                prompt_lengths.append(pl)

        if len(prompt_lengths) >= 2:
            # 如果长度递减（先长后短），倾向自顶向下
            if prompt_lengths[0] > prompt_lengths[-1] * 1.5:
                profile["thinking_structure"] = "自顶向下 - 先框架后细节"
            elif prompt_lengths[-1] > prompt_lengths[0] * 1.5:
                profile["thinking_structure"] = "自底向上 - 从具体问题出发逐步构建"
            else:
                profile["thinking_structure"] = "混合型 - 根据场景灵活切换"
        else:
            profile["thinking_structure"] = "混合型 - 样本不足"
    else:
        profile["thinking_structure"] = "混合型 - 样本不足，默认假设灵活"

    # ---- ai_collaboration_habit: AI协同习惯 ----
    total_ai_output = (
        _safe_count_events_by_type(events, "AI_RESPONSE_RECV") +
        _safe_count_events_by_type(events, "AI_OUTPUT_ACCEPT")
    )
    edit_count = _safe_count_events_by_type(events, "AI_OUTPUT_EDIT")

    if total_ai_output > 0:
        edit_ratio = edit_count / total_ai_output
        if edit_ratio > 0.5:
            profile["ai_collaboration_habit"] = "审校型 - 大量修改AI输出"
        elif edit_ratio < 0.2:
            profile["ai_collaboration_habit"] = "依赖型 - 以采纳AI输出为主"
        else:
            profile["ai_collaboration_habit"] = "协作型 - 选择性采纳与修改"
    else:
        profile["ai_collaboration_habit"] = "依赖型 - 无AI交互记录"

    # ---- complexity_capacity: 复杂度承载 ----
    # 基于 Stage 2 应对突发事件（pivot）的行为
    stage2_events = _safe_find_events_by_stage(events, 2)
    stage2_prompts = _safe_find_events_by_type(stage2_events, "AI_PROMPT_SEND")
    stage2_transition = _safe_get_first(events, "STAGE_TRANSITION", stage=2)

    if stage2_transition and stage2_prompts:
        trans_ts = _parse_timestamp(stage2_transition.get("timestamp", ""))
        first_prompt_ts = _parse_timestamp(stage2_prompts[0].get("timestamp", ""))
        if trans_ts > 0 and first_prompt_ts > 0:
            delay = first_prompt_ts - trans_ts
            if delay <= 60:
                profile["complexity_capacity"] = "高适应 - 对需求变更能快速调整"
            elif delay <= 120:
                profile["complexity_capacity"] = "中适应 - 需要较长时间调整策略"
            else:
                profile["complexity_capacity"] = "低适应 - 对变化反应不足"
        else:
            profile["complexity_capacity"] = "中适应 - 无法精确计算延迟时间"
    elif stage2_prompts:
        # 有 prompt 但无法定位 transition，保守判断
        profile["complexity_capacity"] = "中适应 - 有一定应对能力"
    else:
        # Stage 2 无 AI 交互，可能未注意到变化
        profile["complexity_capacity"] = "低适应 - 对变化反应不足"

    # ---- ownership: 所有权/责任感 ----
    text_input_count = _safe_count_events_by_type(events, "TEXT_INPUT")
    all_input_events = (
        text_input_count +
        _safe_count_events_by_type(events, "COPY_PASTE") +
        _safe_count_events_by_type(events, "AI_OUTPUT_ACCEPT")
    )
    if all_input_events > 0:
        text_input_ratio = text_input_count / all_input_events
        if text_input_ratio > 0.5:
            profile["ownership"] = "强主导 - 大量自主内容产出"
        elif text_input_ratio < 0.2:
            profile["ownership"] = "弱主导 - 依赖AI生成内容"
        else:
            profile["ownership"] = "中主导 - 有一定自主内容配合AI输出"
    else:
        profile["ownership"] = "弱主导 - 无明显自主内容"

    # ---- risk_preference: 风险偏好 ----
    # 基于 undo/redo + error + 尝试非标准模式
    undo_count = _safe_count_events_by_type(events, "UNDO_REDO")
    error_count = _safe_count_events_by_type(events, "ERROR_ENCOUNTERED")

    # 如果有较高比例的 undo 或 error，表示愿意尝试
    if events and (undo_count + error_count) / len(events) > 0.1:
        profile["risk_preference"] = "探索型 - 愿意尝试非常规方案"
    elif undo_count + error_count == 0:
        profile["risk_preference"] = "稳健型 - 偏好成熟方案"
    else:
        profile["risk_preference"] = "稳健型 - 偏好成熟方案"

    # ---- correction_ability: 修正能力 ----
    if undo_count >= 3 or error_count >= 2:
        profile["correction_ability"] = "强修正 - 频繁自我纠正和迭代"
    elif undo_count + error_count == 0:
        profile["correction_ability"] = "弱修正 - 很少回头修改"
    else:
        profile["correction_ability"] = "中修正 - 有一定自我纠正行为"

    # ---- authenticity_risk: 真实性风险 ----
    # 基于矛盾数量，在 detect_contradictions 结果之外做独立评估
    contradictions = detect_contradictions(events, interactions)
    smooth_detected = any(c.type == SMOOTH_OVER_LABEL for c in contradictions)

    if len(contradictions) >= 3 or smooth_detected:
        profile["authenticity_risk"] = "较高 - 多个行为信号表明可能存在过度包装"
    elif len(contradictions) >= 1:
        profile["authenticity_risk"] = "较低 - 行为轨迹自然，存在个别信号"
    else:
        profile["authenticity_risk"] = "较低 - 行为轨迹自然，未发现明显矛盾"

    return profile


# ============================================================================
# 置信度评估
# ============================================================================

def assess_confidence(scores: dict, average_score: float, contradictions: list) -> str:
    """
    评估本次评价的置信度水平。

    综合考虑综合得分区间、维度分差、矛盾信号数量等因素，
    为管理员提供评估结果的可靠性判断及操作建议。

    Args:
        scores: 六维度评分字典
        average_score: 平均分 (1~4 区间)
        contradictions: 矛盾信号列表

    Returns:
        置信度评语字符串，包含等级与建议
    """
    comprehensive = average_score * 4

    # ---- 极端区间：高分/低分必须标注 ----
    if comprehensive >= 13:
        return "较高 - 综合得分处于高分区间，建议结合面试交叉验证确认"
    if comprehensive <= 7:
        return "较低 - 综合得分偏低，可能因任务不适应或环境因素影响"

    # ---- 维度分差过大 ----
    if scores:
        score_values = list(scores.values())
        if score_values:
            spread = max(score_values) - min(score_values)
            if spread >= 2:
                return "中等 - 维度分差较大，属非均衡型候选人，建议关注薄弱维度"

    # ---- 矛盾信号数量 ----
    contradiction_count = len(contradictions) if contradictions else 0
    if contradiction_count >= 3:
        return "需关注 - 存在多个行为矛盾信号，建议人工复核"
    if contradiction_count >= 1:
        return "一般 - 存在少量行为信号，建议结合其他评估方式"

    return "较高 - 行为数据充足且一致性强"
