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


# === 评估 ===

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
    dimension_scores: DimensionScores
    contradictions: list[Contradiction]
    cognitive_profile: CognitiveProfile
    average_score: float
    comprehensive_score: float
    level: Level
    confidence: str
    created_at: str
