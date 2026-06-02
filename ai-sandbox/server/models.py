# AI 沙盒行为洞察系统 数据模型
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# === 枚举 ===

class EventType(str, Enum):
    TASK_START = "TASK_START"
    TASK_SUBMIT = "TASK_SUBMIT"
    AI_PROMPT_SEND = "AI_PROMPT_SEND"
    AI_RESPONSE_RECV = "AI_RESPONSE_RECV"
    AI_OUTPUT_EDIT = "AI_OUTPUT_EDIT"
    AI_OUTPUT_ACCEPT = "AI_OUTPUT_ACCEPT"
    TEXT_INPUT = "TEXT_INPUT"
    TEXT_DELETE = "TEXT_DELETE"
    COPY_PASTE = "COPY_PASTE"
    TAB_SWITCH = "TAB_SWITCH"
    UNDO_REDO = "UNDO_REDO"
    SCROLL = "SCROLL"
    STAGE_TRANSITION = "STAGE_TRANSITION"
    ERROR_ENCOUNTERED = "ERROR_ENCOUNTERED"


class CandidateStatus(str, Enum):
    PENDING = "pending"
    TESTING = "testing"
    COMPLETED = "completed"
    EVALUATED = "evaluated"


class Level(str, Enum):
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"


# === 行为事件 ===

class BehaviorEvent(BaseModel):
    event_id: str
    candidate_id: str
    session_id: str
    timestamp: str  # ISO 8601
    event_type: EventType
    stage: int = Field(ge=1, le=3)
    metadata: dict[str, Any] = Field(default_factory=dict)


class BehaviorEventBatch(BaseModel):
    events: list[BehaviorEvent]


# === 候选人 ===

class CandidateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: Optional[str] = Field(default=None, max_length=200)


class Candidate(BaseModel):
    id: str
    name: str
    email: Optional[str] = None
    token: str
    created_at: str
    status: CandidateStatus = CandidateStatus.PENDING


# === AI 聊天 ===

class AIChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    stage: int = Field(ge=1, le=3)
    conversation_id: Optional[str] = None


class AIChatResponse(BaseModel):
    response: str
    response_time_ms: int
    contains_hallucination: bool = False
    conversation_id: str


# === 任务提交 ===

class TaskSubmission(BaseModel):
    final_output: str = ""


# === 阶段提交 ===

class StageSubmission(BaseModel):
    stage: int = Field(ge=1, le=3)
    content: str = ""


class StageSubmissionResponse(BaseModel):
    candidate_id: str
    stage: int
    content: str
    created_at: str


# === 评估 ===

# 新六维度评分框架
class NewDimensionScores(BaseModel):
    problem_definition: float = Field(ge=0, le=100, description="问题定义能力")
    task_decomposition: float = Field(ge=0, le=100, description="任务拆解能力")
    information_acquisition: float = Field(ge=0, le=100, description="信息获取能力")
    hypothesis_construction: float = Field(ge=0, le=100, description="假设构建能力")
    hypothesis_correction: float = Field(ge=0, le=100, description="假设修正能力")
    integrated_judgment: float = Field(ge=0, le=100, description="综合判断力")


# 人机协作风格
class CollaborationStyle(str, Enum):
    DRIVER = "Driver"  # 主导型
    CO_WORKER = "Co-worker"  # 协作型
    DELEGATOR = "Delegator"  # 委托型
    OPERATOR = "Operator"  # 工具型


# CMMI 成熟度等级
class CMMIMaturityLevel(str, Enum):
    L1 = "L1 - 基础提问者"
    L2 = "L2 - 结构化指令设计者"
    L3 = "L3 - 人机工作流搭建者"
    L4 = "L4 - 多智能体管理者"
    L5 = "L5 - 人机协同体系设计者"


# 旧六维度评分（保持向后兼容）
class DimensionScores(BaseModel):
    ai_fluency: float = Field(ge=1, le=4, description="AI流利度")
    human_ai_judgment: float = Field(ge=1, le=4, description="人机判断力")
    architecture_design: float = Field(ge=1, le=4, description="架构设计力")
    hybrid_orchestration: float = Field(ge=1, le=4, description="混合编排力")
    cognitive_depth: float = Field(ge=1, le=4, description="认知深度")
    problem_modeling: float = Field(ge=1, le=4, description="问题建模能力")


class Contradiction(BaseModel):
    type: str
    description: str
    confidence: str  # high / medium / low
    evidence: str


class CognitiveProfile(BaseModel):
    decision_style: str = ""
    thinking_structure: str = ""
    ai_collaboration_habit: str = ""
    complexity_capacity: str = ""
    ownership: str = ""
    risk_preference: str = ""
    correction_ability: str = ""
    authenticity_risk: str = ""


class EvaluationResult(BaseModel):
    candidate_id: str
    candidate_name: str
    narrative_text: str
    
    # 旧评分系统（向后兼容）
    dimension_scores: DimensionScores
    contradictions: list[Contradiction]
    cognitive_profile: CognitiveProfile
    average_score: float
    comprehensive_score: float
    level: Level
    confidence: str
    
    # 新评分系统
    new_dimension_scores: Optional[NewDimensionScores] = None
    collaboration_style: Optional[CollaborationStyle] = None
    cmmi_maturity_level: Optional[CMMIMaturityLevel] = None
    
    created_at: str
