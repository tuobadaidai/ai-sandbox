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

    # ---- 7. "权变思维缺失"检测 ----
    # 核心：检测候选人是否识别到多方矛盾并进行权衡
    # 在公文筐任务中，8封邮件蕴含多个两难矛盾（AIvs人工、直连vs聚合、盈利vs增长、合规vs创新）
    # 如果候选人的产出中只识别了单一维度的利益，未提及矛盾或权衡，则判定权变思维缺失

    # 收集所有 AI prompt 文本，检查是否包含权衡/矛盾/多利益相关方的表述
    all_prompt_texts = []
    for e in events:
        if e.get("event_type") == "AI_PROMPT_SEND":
            meta = e.get("metadata", {}) or {}
            pt = meta.get("prompt_text", "") or meta.get("message", "")
            if pt:
                all_prompt_texts.append(pt)

    # 检测是否出现权衡/矛盾相关的关键表述
    contingency_keywords = [
        "权衡", "两难", "矛盾", "冲突", "平衡", "trade-off",
        "利益相关方", "博弈", "让步", "折中", "权变",
        "短期 vs", "长期 vs", "一方面", "另一方面", "但是",
        "反对", "质疑", "风险", "代价", "取舍", "兼顾",
        "如果……那么", "另一种可能", "不一定"
    ]
    contingency_count = 0
    for text in all_prompt_texts:
        for kw in contingency_keywords:
            if kw in text:
                contingency_count += 1
                break  # 一段文本只计一次

    # 检测候选人的提交内容中是否体现出对矛盾的认知
    submissions_text = ""
    try:
        # 获取候选人ID —— 从事件中提取
        if events:
            cid = events[0].get("candidate_id", "")
            if cid:
                import database as db
                submissions = db.get_all_stage_submissions(cid)
                for s in submissions:
                    submissions_text += (s.get("content", "") or "") + " "
    except Exception:
        pass

    # 在提交内容中也检查权衡关键词
    submission_contingency = 0
    for kw in contingency_keywords:
        if kw in submissions_text:
            submission_contingency += 1

    total_contingency = contingency_count + submission_contingency
    has_multistakeholder = any(
        kw in " ".join(all_prompt_texts)
        for kw in ["利益相关", "多方", "不同角度", "从……看", "对……来说"]
    )

    # 如果 prompt 不少（>=3）但缺乏权衡表述
    if len(all_prompt_texts) >= 3 and total_contingency < 2:
        level = "high" if total_contingency == 0 else "medium"
        contradictions.append(Contradiction(
            type="权变思维缺失",
            description="在包含多方利益冲突的公文筐任务中，未表现出对矛盾关系的识别与权衡",
            confidence=level,
            evidence=(
                f"AI交互{len(all_prompt_texts)}轮, "
                f"权衡相关表述仅{total_contingency}处, "
                f"多方利益相关方表述={'有' if has_multistakeholder else '无'}"
            )
        ))
    elif total_contingency >= 5:
        # 正向信号：表现出较强的权衡思维能力（不生成矛盾，只记录）
        pass

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
        置信度评语言字符串，包含等级与建议
    """
    comprehensive = average_score * 4

    # === 极端区间：高分/低分必须标注 ===
    if comprehensive >= 13:
        return "较高 - 综合得分处于高分区间，建议结合面试交叉验证确认"
    if comprehensive <= 7:
        return "较低 - 综合得分偏低，可能因任务不适应或环境因素影响"

    # === 维度分差过大 ===
    if scores:
        score_values = list(scores.values())
        if score_values:
            spread = max(score_values) - min(score_values)
            if spread >= 2:
                return "中等 - 维度分差较大，属非均衡型候选人，建议关注薄弱维度"

    # === 矛盾信号数量 ===
    contradiction_count = len(contradictions) if contradictions else 0
    if contradiction_count >= 3:
        return "需关注 - 存在多个行为矛盾信号，建议人工复核"
    if contradiction_count >= 1:
        return "一般 - 存在少量行为信号，建议结合其他评估方式"

    return "较高 - 行为数据充足且一致性强"


# ============================================================================
# 协作风格与 CMMI 成熟度检测
# ============================================================================

def detect_collaboration_style(events: list[dict], interactions: list[dict]) -> str:
    """
    检测人机协作风格：Driver / Co-worker / Delegator / Operator

    Args:
        events: 行为事件列表
        interactions: AI 交互记录列表

    Returns:
        协作风格字符串
    """
    # 统计指标
    ai_prompts = [e for e in events if e.get("event_type") == "AI_PROMPT_SEND"]
    text_inputs = [e for e in events if e.get("event_type") == "TEXT_INPUT"]
    edits = [e for e in events if e.get("event_type") == "AI_OUTPUT_EDIT"]
    accepts = [e for e in events if e.get("event_type") == "AI_OUTPUT_ACCEPT"]
    
    total_actions = len(ai_prompts) + len(text_inputs)
    
    if total_actions == 0:
        return "Unknown"
    
    # Driver 型：人工编辑事件先于 AI 调用事件的比例 > 0.6
    # 简化检测：TEXT_INPUT 比例高，且有较多 EDIT
    text_input_ratio = len(text_inputs) / total_actions if total_actions > 0 else 0
    edit_ratio = len(edits) / (len(edits) + len(accepts)) if (len(edits) + len(accepts)) > 0 else 0
    
    if text_input_ratio > 0.6 and edit_ratio > 0.3:
        return "Driver"
    
    # Co-worker 型：追问次数 > 5 且编辑率 > 0.4
    # 简化：多轮对话 + 较多编辑
    follow_up_count = 0
    for i in range(1, len(ai_prompts)):
        curr_meta = ai_prompts[i].get("metadata", {})
        if curr_meta.get("iteration") and curr_meta.get("iteration") > 1:
            follow_up_count += 1
    
    if follow_up_count >= 3 and edit_ratio > 0.4:
        return "Co-worker"
    
    # Delegator 型：单轮对话占比高，编辑率低
    if follow_up_count == 0 and edit_ratio < 0.15:
        return "Delegator"
    
    # Operator 型：默认
    return "Operator"


def detect_cmmi_maturity_level(events: list[dict], interactions: list[dict]) -> str:
    """
    检测 CMMI 成熟度等级（L1-L5）

    Args:
        events: 行为事件列表
        interactions: AI 交互记录列表

    Returns:
        CMMI 成熟度等级字符串
    """
    prompts = [
        e.get("metadata", {}).get("prompt_text", "") 
        for e in events 
        if e.get("event_type") == "AI_PROMPT_SEND"
    ]
    prompts = [p for p in prompts if p]
    
    if not prompts:
        return "L1 - 基础提问者"
    
    # L5 检测：自行设计 AI 使用策略、定义信任边界、建立纠错机制
    l5_keywords = [
        "信任边界", "使用策略", "纠错机制", "验证流程",
        " AI 原则", "使用规范", "质量标准", "风险控制"
    ]
    has_l5 = any(any(kw in p for kw in l5_keywords) for p in prompts)
    if has_l5:
        return "L5 - 人机协同体系设计者"
    
    # L4 检测：让 AI 扮演不同角色交叉验证、自我批判
    l4_keywords = [
        "扮演", "角色", "不同角度", "对立面", "自我批判",
        "反驳", "质疑", "从反面看", "正反两方面"
    ]
    has_l4 = any(any(kw in p for kw in l4_keywords) for p in prompts)
    if has_l4:
        return "L4 - 多智能体管理者"
    
    # L3 检测：将任务拆分为多个子步骤分轮调度 AI
    ai_prompts = [e for e in events if e.get("event_type") == "AI_PROMPT_SEND"]
    if len(ai_prompts) >= 3:
        # 检查是否有明显的分步骤调用
        has_step_keywords = any(
            any(kw in p for kw in ["第一步", "第二步", "接下来", "然后"]) 
            for p in prompts
        )
        if has_step_keywords:
            return "L3 - 人机工作流搭建者"
    
    # L2 检测：包含角色设定、格式约束、输出范围限定
    l2_keywords = [
        "你是", "作为", "请以", "格式", "JSON", "表格",
        "列表", "不要", "仅限于", "范围"
    ]
    has_l2 = any(any(kw in p for kw in l2_keywords) for p in prompts)
    if has_l2:
        return "L2 - 结构化指令设计者"
    
    # L1：默认
    return "L1 - 基础提问者"


# ============================================================================
# Work DNA 能力画像生成
# ============================================================================

DIMS_LABEL = {
    "problem_definition": "问题定义能力",
    "task_decomposition": "任务拆解能力",
    "information_acquisition": "信息获取能力",
    "hypothesis_construction": "假设构建能力",
    "hypothesis_correction": "假设修正能力",
    "integrated_judgment": "综合判断力",
}

STYLE_MAP = {
    "Driver": "主导型协作——擅长先建立分析框架再调用AI执行细节。在信息过载场景中能保持清晰的认知主导权，但需注意避免在AI擅长的领域过度干预。",
    "Co-worker": "协作型协同——将AI视为平等的工作伙伴，通过高频互动和联合推理持续优化产出。这种模式在复杂分析和创新任务中效率最高。",
    "Delegator": "委托型外包——倾向于将完整任务委托给AI并接受首轮输出。在常规任务中效率较高，但在需要深度判断的场景中可能遗漏关键矛盾。",
    "Operator": "工具型使用——主要将AI用于摘要、翻译、格式化等基础工作。未充分释放AI在高阶认知工作中的潜力。",
}

CMMI_MAP = {
    "L1": "基础提问者——停留在简单的单一指令模式，尚未学会结构化地引导AI协同工作。",
    "L2": "结构化指令设计者——能够为AI设定角色和输出格式，具备初步的结构化思维。",
    "L3": "人机工作流搭建者——能将复杂任务拆分为多步骤工作流，分阶段调度AI。这标志着从会用AI到善用AI的质变。",
    "L4": "多智能体管理者——能够引导AI扮演不同视角角色进行交叉验证和自我批判。这是高管级人机协同的关键分水岭。",
    "L5": "人机协同体系设计者——不仅能高效协同AI，还能自主设计原则、定义信任边界、建立纠错机制。标志着具备将AI融入组织决策体系的能力。",
}

BASELINE = {
    "problem_definition": 82,
    "task_decomposition": 80,
    "information_acquisition": 85,
    "hypothesis_construction": 78,
    "hypothesis_correction": 75,
    "integrated_judgment": 83,
}

SUGGESTIONS = {
    "问题定义能力": "建议在任务开始时先用自己的话重新定义问题，而非直接沿用任务描述。可以尝试问AI「这个描述背后还有哪些更深层的矛盾」。",
    "任务拆解能力": "建议在调用AI前先将大任务拆为3-5个子任务，每个子任务单独与AI交互。",
    "信息获取能力": "建议增加追问频率——对AI输出的关键数据和假设至少追问两次。建立先质疑再接受的习惯。",
    "假设构建能力": "建议在信息不完整时先提出自己的假设再让AI验证，而非直接让AI给出结论。",
    "假设修正能力": "建议在AI给出新信息后主动回顾之前的判断，有意识地做如果新信息是对的之前结论需要改什么的思维练习。",
    "综合判断力": "建议在决策前画出利益相关方地图，对每个选项列出二阶效应和风险缓解措施后再做判断。",
}


def generate_work_dna_portrait(new_dimension_scores, collaboration_style, cmmi_level, stage_submissions=None):
    """
    生成 Work DNA 能力画像 Markdown 文案。
    """
    scores = new_dimension_scores or {}
    if scores:
        avg = sum(scores.values()) / len(scores)
    else:
        avg = 0

    if avg >= 85:
        tier, tier_desc = "卓越", "在面向复杂商业场景的人机协同任务中展现出顶级认知能力"
    elif avg >= 70:
        tier, tier_desc = "优秀", "具备扎实的人机协同框架思维，能够独立驱动AI完成高价值工作"
    elif avg >= 55:
        tier, tier_desc = "合格", "具备基础的人机协作能力，在特定维度上有提升空间"
    elif avg >= 40:
        tier, tier_desc = "发展中", "AI协同模式尚未成型，需要通过系统性训练构建方法论"
    else:
        tier, tier_desc = "基础", "尚未建立有效的人机协作工作范式，建议从基础提示工程培训开始"

    # 优势 / 待提升
    strengths = []
    weaknesses = []
    for key, label in DIMS_LABEL.items():
        val = scores.get(key, 0)
        if val >= 80:
            strengths.append((label, val))
        elif val < 50 or (not strengths and val <= 55):
            weaknesses.append((label, val))
    if not strengths:
        strengths.append(("综合表现", avg))
    if not weaknesses:
        sorted_dims = sorted(scores.items(), key=lambda x: x[1])
        weakest = sorted_dims[0] if sorted_dims else ("综合表现", avg)
        weaknesses.append((DIMS_LABEL.get(weakest[0], weakest[0]), weakest[1]))

    parts = []
    parts.append("## Work DNA 能力画像")
    parts.append("")
    parts.append("### 总体评定：" + tier + "级别")
    parts.append("")
    parts.append(tier_desc + "。新六维度综合均分 **{:.1f}/100**。".format(avg))
    parts.append("")

    parts.append("### 核心能力图谱")
    parts.append("")
    parts.append("**优势维度：**")
    for label, score in strengths:
        parts.append("- **" + label + "**：" + str(score) + "分 —— 在该维度展现出显著能力优势")
    parts.append("")
    parts.append("**待提升维度：**")
    for label, score in weaknesses:
        sug = SUGGESTIONS.get(label, "建议在该维度增加刻意练习。")
        parts.append("- **" + label + "**：" + str(score) + "分 —— " + sug)

    cs = collaboration_style or "Unknown"
    style_text = STYLE_MAP.get(cs, "未检测到明确的协作风格。")
    parts.append("")
    parts.append("### 人机协作风格：" + cs + "型")
    parts.append("")
    parts.append(style_text)

    cmmi_num = cmmi_level[0:2] if cmmi_level else "L1"
    cmmi_text = CMMI_MAP.get(cmmi_num, "当前处于 " + str(cmmi_num) + " 级。")
    parts.append("")
    parts.append("### AI协同成熟度：" + str(cmmi_level))
    parts.append("")
    parts.append(cmmi_text)

    # 发展建议
    parts.append("")
    parts.append("### 发展建议")
    parts.append("")
    plan = []
    cmmi_int = int(cmmi_num[1]) if cmmi_num and len(cmmi_num) >= 2 else 1
    if cmmi_int <= 1:
        plan.append("【优先】学习基础提示工程：给AI设定角色、明确输出格式和约束条件。")
    elif cmmi_int == 2:
        plan.append("【优先】尝试将复杂任务拆分为多个子步骤，每步单独与AI交互，构建人机工作流。")
    elif cmmi_int == 3:
        plan.append("【优先】练习让AI扮演不同角色对同一问题进行辩论和交叉验证。")
    elif cmmi_int >= 4:
        plan.append("【优先】将个人AI使用经验总结为组织级的AI协同操作手册，推动团队能力升级。")
    if scores:
        weakest_dim = min(scores, key=scores.get)
        weakest_label = DIMS_LABEL.get(weakest_dim, weakest_dim)
        plan.append("最弱维度是「" + weakest_label + "」（" + str(scores[weakest_dim]) + "分），建议作为下季度重点发展目标。")
    if cs == "Delegator":
        plan.append("委托型风格效率占优，但建议对AI关键输出至少做1-2处实质性修改以提升深度。")
    elif cs == "Operator":
        plan.append("建议每周尝试1-2次将AI用于分析型、判断型任务，逐步拓展协同深度。")
    for s in plan:
        parts.append("- " + s)

    # 对标表
    parts.append("")
    parts.append("### 高绩效人才行为库对标")
    parts.append("")
    parts.append("| 维度 | 当前 | 高绩效基准 | 差距 |")
    parts.append("|------|------|-----------|------|")
    for key, label in DIMS_LABEL.items():
        current = scores.get(key, 0)
        baseline = BASELINE.get(key, 85)
        gap = baseline - current
        gap_str = "-" + str(gap) if gap > 0 else "+" + str(-gap)
        parts.append("| " + label + " | " + str(current) + " | " + str(baseline) + " | " + gap_str + " |")

    return "\n".join(parts)
