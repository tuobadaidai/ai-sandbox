# AI 沙盒行为洞察系统 - FastAPI 入口
import json
import secrets
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Depends, Query, Header, Body, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

import config
from models import (
    CandidateCreate, BehaviorEventBatch, AIChatRequest,
    AIChatResponse, EvaluationResult, TaskSubmission,
    StageSubmission, StageSubmissionResponse,
    AdminLoginRequest, AdminLoginResponse
)
import database as db
from services import ai_service, behavior_analyzer, evaluation_engine
from services.config_service import ConfigService

app = FastAPI(title="AI 沙盒行为洞察系统", version="1.0.0")

# CORS：根据环境变量动态配置，默认仅允许同源
_cors_origins = config.CORS_ORIGINS.split(",") if config.CORS_ORIGINS else []
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins if _cors_origins else [],  # 无配置则不允许跨域
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "Authorization", "X-Token", "X-Admin-Session"],
    allow_credentials=True if _cors_origins else False,
)

# 前端静态文件
frontend_dir = Path(config.FRONTEND_DIR)
app.mount("/css", StaticFiles(directory=str(frontend_dir / "css")), name="css")
app.mount("/js", StaticFiles(directory=str(frontend_dir / "js")), name="js")


# === 依赖注入 ===

async def get_candidate_by_token(token: str = Header(..., alias="X-Token")) -> dict:
    candidate = db.get_candidate_by_token(token)
    if not candidate:
        raise HTTPException(401, "无效的访问凭证")
    return candidate


async def verify_admin(session_id: str = Header(..., alias="X-Admin-Session")) -> bool:
    """管理员认证：通过 Header 传递 session_id，不再走 Query 参数"""
    if not db.verify_admin_session(session_id):
        raise HTTPException(401, "管理员会话无效或已过期，请重新登录")
    return True


# === 静态页面 ===

@app.get("/")
async def index():
    return FileResponse(frontend_dir / "index.html")


# === 候选人流程 ===

@app.post("/api/candidates")
async def create_candidate(data: CandidateCreate):
    candidate_id = f"cand_{secrets.token_hex(8)}"
    token = secrets.token_urlsafe(config.TOKEN_LENGTH)
    candidate = db.create_candidate(data.name, data.email, token, candidate_id)
    return {"id": candidate["id"], "name": candidate["name"], "token": token}


@app.get("/api/sandbox/{token}")
async def get_sandbox(token: str):
    candidate = db.get_candidate_by_token(token)
    if not candidate:
        raise HTTPException(404, "候选人不存在")

    if candidate["status"] == "completed":
        raise HTTPException(400, "任务已完成")

    if candidate["status"] == "pending":
        db.update_candidate_status(candidate["id"], "testing")

    # 加载任务配置
    task_path = config.TASKS_DIR / config.DEFAULT_TASK
    with open(task_path, "r", encoding="utf-8") as f:
        task_config = json.load(f)

    # 获取已有的阶段提交
    stage_submissions = db.get_all_stage_submissions(candidate["id"])
    stage_submissions_dict = {s["stage"]: s["content"] for s in stage_submissions}

    return {
        "candidate_id": candidate["id"],
        "candidate_name": candidate["name"],
        "task": task_config,
        "session_id": f"sess_{secrets.token_hex(4)}",
        "stage_submissions": stage_submissions_dict
    }


@app.post("/api/events/{token}")
async def upload_events(token: str, batch: BehaviorEventBatch):
    candidate = db.get_candidate_by_token(token)
    if not candidate:
        raise HTTPException(401, "无效的访问凭证")

    events_data = [e.model_dump() for e in batch.events]
    db.save_events(events_data)
    return {"saved": len(events_data)}


@app.post("/api/ai/chat/{token}", response_model=AIChatResponse)
async def ai_chat(token: str, data: AIChatRequest):
    candidate = db.get_candidate_by_token(token)
    if not candidate:
        raise HTTPException(401, "无效的访问凭证")

    start_time = time.time()

    # 调用 AI 服务（DashScope / Ollama 双后端）
    response_text, contains_hallucination = await ai_service.chat_with_ai(
        data.message, data.stage, getattr(data, "conversation_id", None)
    )

    response_time_ms = int((time.time() - start_time) * 1000)

    # 保存 AI 交互记录
    db.save_ai_interaction(
        candidate_id=candidate["id"],
        stage=data.stage,
        prompt=data.message,
        response=response_text,
        prompt_length=len(data.message),
        response_length=len(response_text),
        response_time_ms=response_time_ms,
        contains_hallucination=contains_hallucination
    )

    return AIChatResponse(
        response=response_text,
        response_time_ms=response_time_ms,
        contains_hallucination=contains_hallucination,
        conversation_id=data.conversation_id or f"conv_{secrets.token_hex(4)}"
    )


@app.post("/api/stages/submit/{token}")
async def submit_stage(token: str, submission: StageSubmission):
    candidate = db.get_candidate_by_token(token)
    if not candidate:
        raise HTTPException(401, "无效的访问凭证")

    db.save_stage_submission(candidate["id"], submission.stage, submission.content)

    db.save_events([{
        "candidate_id": candidate["id"],
        "session_id": "",
        "timestamp": db.now_iso(),
        "event_type": "STAGE_SUBMIT",
        "stage": submission.stage,
        "metadata": {"content_length": len(submission.content)}
    }])

    return {"status": "saved", "candidate_id": candidate["id"], "stage": submission.stage}


@app.post("/api/submit/{token}")
async def submit_task(token: str, submission: TaskSubmission = Body(default=None)):
    candidate = db.get_candidate_by_token(token)
    if not candidate:
        raise HTTPException(401, "无效的访问凭证")

    db.update_candidate_status(candidate["id"], "completed")

    # 保存最终产出
    final_output = submission.final_output if submission else ""
    if final_output:
        db.save_events([{
            "candidate_id": candidate["id"],
            "session_id": "",
            "timestamp": db.now_iso(),
            "event_type": "TASK_SUBMIT",
            "stage": 3,
            "metadata": {"final_output_length": len(final_output)}
        }])

    return {"status": "completed", "candidate_id": candidate["id"]}


@app.post("/api/heartbeat/{token}")
async def candidate_heartbeat(token: str):
    """候选人心跳接口，前端每 60 秒调用一次。
    
    用途：
    - 记录候选人活跃状态（服务端埋点，无法伪造）
    - 检测候选人是否中途离开
    - 评估专注度和时间管理能力
    """
    candidate = db.get_candidate_by_token(token)
    if not candidate:
        raise HTTPException(401, "无效的访问凭证")

    db.save_events([{
        "candidate_id": candidate["id"],
        "session_id": "",
        "timestamp": db.now_iso(),
        "event_type": "HEARTBEAT",
        "stage": 0,
        "metadata": {"source": "heartbeat"}
    }])

    return {"status": "ok", "timestamp": db.now_iso()}


# === 管理员登录 ===

@app.post("/api/admin/login", response_model=AdminLoginResponse)
async def admin_login(data: AdminLoginRequest):
    """管理员登录，返回会话 token。密码不再通过 URL 传递。"""
    if not db.verify_admin(data.secret):
        raise HTTPException(401, "管理密码错误")
    session_id = db.create_admin_session()
    return AdminLoginResponse(
        session_id=session_id,
        expires_in=config.ADMIN_SESSION_EXPIRY
    )


@app.post("/api/admin/logout")
async def admin_logout(session_id: str = Header(..., alias="X-Admin-Session")):
    """管理员登出，销毁会话"""
    with db.db_conn() as conn:
        conn.execute("DELETE FROM admin_sessions WHERE session_id = ?", (session_id,))
        conn.commit()
    return {"status": "logged_out"}


# === 管理后台 ===

@app.get("/api/admin/candidates")
async def admin_list_candidates(_=Depends(verify_admin)):
    candidates = db.list_candidates()
    # 附加评估状态
    for c in candidates:
        ev = db.get_evaluation(c["id"])
        c["has_evaluation"] = ev is not None
        c["level"] = ev["level"] if ev else None
    return candidates


@app.get("/api/admin/candidates/{candidate_id}/events")
async def admin_get_events(candidate_id: str, _=Depends(verify_admin)):
    candidate = db.get_candidate_by_id(candidate_id)
    if not candidate:
        raise HTTPException(404, "候选人不存在")
    events = db.get_events(candidate_id)
    interactions = db.get_ai_interactions(candidate_id)
    return {"candidate": candidate, "events": events, "ai_interactions": interactions}


@app.post("/api/admin/candidates/{candidate_id}/evaluate")
async def admin_evaluate(candidate_id: str, _=Depends(verify_admin)):
    candidate = db.get_candidate_by_id(candidate_id)
    if not candidate:
        raise HTTPException(404, "候选人不存在")

    events = db.get_events(candidate_id)
    interactions = db.get_ai_interactions(candidate_id)

    if not events:
        raise HTTPException(400, "没有行为数据，无法评估")

    # 1. 翻译行为数据为叙事文本
    narrative = behavior_analyzer.translate_to_narrative(events, interactions, candidate)

    # 2. 计算六维度分数（旧版）
    scores = behavior_analyzer.calculate_dimension_scores(events, interactions)

    # 3. 计算新六维度评分（高管测评）
    new_scores = behavior_analyzer.calculate_new_dimension_scores(events, interactions)

    # 4. 矛盾检测
    contradictions = evaluation_engine.detect_contradictions(events, interactions)

    # 5. 生成认知画像
    cognitive_profile = evaluation_engine.generate_cognitive_profile(events, interactions, scores)

    # 6. 检测协作风格和 CMMI 成熟度
    collaboration_style = evaluation_engine.detect_collaboration_style(events, interactions)
    cmmi_maturity = evaluation_engine.detect_cmmi_maturity_level(events, interactions)

    # 7. 生成 Work DNA 能力画像
    stage_submissions = db.get_all_stage_submissions(candidate_id)
    work_dna = evaluation_engine.generate_work_dna_portrait(
        new_scores, collaboration_style, cmmi_maturity, stage_submissions
    )

    # 7. 计算综合得分和级别（使用加权平均）
    weighted_score = sum(
        scores[k] * behavior_analyzer.DIMENSION_WEIGHTS.get(k, 1.0/6)
        for k in scores
    )
    average_score = sum(scores.values()) / len(scores)  # 保留简单平均用于兼容

    comprehensive_score = weighted_score * 4  # 映射到 0~16 分制

    level = behavior_analyzer.determine_level(weighted_score)
    confidence = evaluation_engine.assess_confidence(scores, weighted_score, contradictions)

    # 保存评估结果（包含新旧评分）
    db.save_evaluation(
        candidate_id=candidate_id,
        narrative=narrative,
        dimension_scores=scores,
        contradictions=[c.model_dump() for c in contradictions],
        cognitive_profile=cognitive_profile,
        average_score=round(average_score, 2),
        comprehensive_score=round(comprehensive_score, 1),
        level=level,
        confidence=confidence,
        new_dimension_scores=new_scores,
        collaboration_style=collaboration_style,
        cmmi_maturity_level=cmmi_maturity,
        work_dna_portrait=work_dna
    )

    return {
        "status": "evaluated",
        "level": level,
        "average_score": round(average_score, 2),
        "comprehensive_score": round(comprehensive_score, 1)
    }


@app.get("/api/admin/candidates/{candidate_id}/report")
async def admin_get_report(candidate_id: str, _=Depends(verify_admin)):
    candidate = db.get_candidate_by_id(candidate_id)
    if not candidate:
        raise HTTPException(404, "候选人不存在")

    evaluation = db.get_evaluation(candidate_id)
    stage_submissions = db.get_all_stage_submissions(candidate_id)
    if not evaluation:
        raise HTTPException(404, "尚未评估，请先触发评估")

    return {
        "candidate": candidate,
        "evaluation": evaluation,
        "stage_submissions": stage_submissions
    }


@app.get("/api/admin/candidates/{candidate_id}/evaluations")
async def admin_get_evaluation_versions(candidate_id: str, _=Depends(verify_admin)):
    """获取候选人所有评估版本"""
    candidate = db.get_candidate_by_id(candidate_id)
    if not candidate:
        raise HTTPException(404, "候选人不存在")
    versions = db.get_evaluation_versions(candidate_id)
    return {"candidate_id": candidate_id, "versions": versions}


@app.get("/api/admin/candidates/{candidate_id}/evaluations/{version}")
async def admin_get_evaluation_by_version(candidate_id: str, version: int, _=Depends(verify_admin)):
    """获取候选人指定版本的评估"""
    evaluation = db.get_evaluation(candidate_id, version)
    if not evaluation:
        raise HTTPException(404, f"版本 {version} 不存在")
    return {"candidate_id": candidate_id, "evaluation": evaluation}


# === 系统配置 API ===

cfg = ConfigService()


@app.get("/api/admin/config/ai")
async def admin_get_ai_config(_=Depends(verify_admin)):
    """获取当前 AI 配置（API Key 脱敏）"""
    return cfg.get("ai")


@app.put("/api/admin/config/ai")
async def admin_update_ai_config(request: Request, _=Depends(verify_admin)):
    """更新 AI 配置"""
    body = await request.json()
    # 验证 provider 合法性
    if "provider" in body and body["provider"] not in ("dashscope", "ollama", "mock", None):
        raise HTTPException(400, "provider 必须是 dashscope/ollama/mock")
    cfg.set_batch("ai", body)
    return {"status": "ok", "message": "AI 配置已更新"}


@app.post("/api/admin/config/ai/test")
async def admin_test_ai_connection(_=Depends(verify_admin)):
    """测试当前 AI 连接"""
    import asyncio
    try:
        from services.ai_provider import create_provider
        provider = create_provider()
        start = time.time()
        result = await provider.chat("你好，请简短回复", 1, "你是一个测试助手，请简短回复。")
        elapsed = round((time.time() - start) * 1000)
        return {
            "success": True,
            "provider": provider.name,
            "response_time_ms": elapsed,
            "test_response": result[:200]
        }
    except Exception as e:
        return {
            "success": False,
            "provider": str(e),
            "response_time_ms": 0,
            "test_response": None,
            "error": str(e)
        }


@app.get("/api/admin/config/tasks")
async def admin_list_tasks(_=Depends(verify_admin)):
    """获取题本列表"""
    tasks_dir = config.TASKS_DIR
    task_files = sorted(tasks_dir.glob("*.json")) if tasks_dir.exists() else []
    active_task = cfg.get("task", "active_task", config.DEFAULT_TASK)
    tasks = []
    for f in task_files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            tasks.append({
                "filename": f.name,
                "name": data.get("name", f.name),
                "description": data.get("description", ""),
                "duration_minutes": data.get("duration_minutes", 0),
                "stages_count": len(data.get("stages", [])),
                "is_active": f.name == active_task
            })
        except Exception:
            tasks.append({"filename": f.name, "name": f.name, "error": "parse_error", "is_active": f.name == active_task})
    return {"tasks": tasks, "active_task": active_task}


@app.get("/api/admin/config/tasks/active")
async def admin_get_active_task(_=Depends(verify_admin)):
    """获取当前活跃题本详情"""
    active_task = cfg.get("task", "active_task", config.DEFAULT_TASK)
    task_path = config.TASKS_DIR / active_task
    if not task_path.exists():
        raise HTTPException(404, f"题本文件 {active_task} 不存在")
    return json.loads(task_path.read_text(encoding="utf-8"))


@app.get("/api/admin/config/tasks/{filename}")
async def admin_get_task(filename: str, _=Depends(verify_admin)):
    """获取指定题本内容"""
    task_path = config.TASKS_DIR / filename
    if not task_path.exists():
        raise HTTPException(404, f"题本文件 {filename} 不存在")
    return json.loads(task_path.read_text(encoding="utf-8"))


@app.put("/api/admin/config/tasks/active")
async def admin_set_active_task(request: Request, _=Depends(verify_admin)):
    """切换活跃题本"""
    body = await request.json()
    filename = body.get("filename")
    if not filename:
        raise HTTPException(400, "缺少 filename")
    task_path = config.TASKS_DIR / filename
    if not task_path.exists():
        raise HTTPException(404, f"题本文件 {filename} 不存在")
    # 验证 JSON 合法性
    try:
        json.loads(task_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        raise HTTPException(400, f"题本文件 {filename} JSON 格式错误")
    cfg.set("task", "active_task", filename)
    return {"status": "ok", "active_task": filename}


@app.post("/api/admin/config/tasks")
async def admin_create_task(request: Request, _=Depends(verify_admin)):
    """创建新题本"""
    body = await request.json()
    filename = body.get("filename")
    content = body.get("content")
    if not filename or not content:
        raise HTTPException(400, "缺少 filename 或 content")
    if not filename.endswith(".json"):
        filename += ".json"
    task_path = config.TASKS_DIR / filename
    if task_path.exists():
        raise HTTPException(409, f"题本 {filename} 已存在")
    # 验证 JSON
    try:
        json.loads(content) if isinstance(content, str) else content
    except json.JSONDecodeError:
        raise HTTPException(400, "content 不是合法的 JSON")
    task_path.write_text(content if isinstance(content, str) else json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"status": "ok", "filename": filename}


@app.put("/api/admin/config/tasks/{filename}")
async def admin_update_task(filename: str, request: Request, _=Depends(verify_admin)):
    """编辑题本"""
    body = await request.json()
    content = body.get("content")
    if not content:
        raise HTTPException(400, "缺少 content")
    task_path = config.TASKS_DIR / filename
    if not task_path.exists():
        raise HTTPException(404, f"题本 {filename} 不存在")
    try:
        json.loads(content) if isinstance(content, str) else content
    except json.JSONDecodeError:
        raise HTTPException(400, "content 不是合法的 JSON")
    task_path.write_text(content if isinstance(content, str) else json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"status": "ok"}


@app.delete("/api/admin/config/tasks/{filename}")
async def admin_delete_task(filename: str, _=Depends(verify_admin)):
    """删除题本（不能删除当前活跃题本）"""
    active_task = cfg.get("task", "active_task", config.DEFAULT_TASK)
    if filename == active_task:
        raise HTTPException(400, "不能删除当前活跃题本，请先切换")
    task_path = config.TASKS_DIR / filename
    if not task_path.exists():
        raise HTTPException(404, f"题本 {filename} 不存在")
    task_path.unlink()
    return {"status": "ok"}


@app.post("/api/admin/config/tasks/{filename}/copy")
async def admin_copy_task(filename: str, request: Request, _=Depends(verify_admin)):
    """复制题本"""
    body = await request.json()
    new_filename = body.get("filename", filename.replace(".json", "_copy.json"))
    if not new_filename.endswith(".json"):
        new_filename += ".json"
    src = config.TASKS_DIR / filename
    dst = config.TASKS_DIR / new_filename
    if not src.exists():
        raise HTTPException(404, f"题本 {filename} 不存在")
    if dst.exists():
        raise HTTPException(409, f"题本 {new_filename} 已存在")
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return {"status": "ok", "filename": new_filename}


@app.get("/api/admin/config/evaluation")
async def admin_get_evaluation_config(_=Depends(verify_admin)):
    """获取评估维度配置"""
    return cfg.get("evaluation")


@app.put("/api/admin/config/evaluation")
async def admin_update_evaluation_config(request: Request, _=Depends(verify_admin)):
    """更新评估维度配置"""
    body = await request.json()
    # 校验权重总和
    if "dimension_weights" in body:
        weights = body["dimension_weights"]
        total = sum(weights.values())
        if abs(total - 1.0) > 0.01:
            raise HTTPException(400, f"权重总和必须为 1.0，当前为 {total:.2f}")
    # 校验阈值单调递增
    if "level_thresholds" in body:
        t = body["level_thresholds"]
        if not (t.get("L1", 0) < t.get("L2", 999) < t.get("L3", 9999)):
            raise HTTPException(400, "阈值必须满足 L1 < L2 < L3")
    cfg.set_batch("evaluation", body)
    return {"status": "ok", "message": "评估配置已更新"}


@app.post("/api/admin/config/evaluation/reset")
async def admin_reset_evaluation_config(_=Depends(verify_admin)):
    """重置评估配置为默认值"""
    cfg.reset_category("evaluation")
    return {"status": "ok", "message": "评估配置已重置为默认值"}


@app.get("/api/admin/config/changelog")
async def admin_get_config_changelog(category: str = None, limit: int = 50, _=Depends(verify_admin)):
    """获取配置变更历史"""
    return {"changelog": cfg.get_changelog(category, limit)}


# === 启动 ===

@app.on_event("startup")
def startup():
    db.init_db()


# === 服务端行为追踪中间件 ===
# 自动记录 API 访问模式，作为客户端追踪的补充，防止行为数据被篡改

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class BehaviorTrackingMiddleware(BaseHTTPMiddleware):
    """服务端行为追踪中间件
    
    自动记录候选人 API 调用模式：
    - AI 对话频率和时机
    - 沙盒访问模式
    - 阶段切换行为
    - 提交模式（是否反复修改）
    
    与客户端埋点互补：
    - 客户端追踪：详细交互（点击、输入、滚动、复制粘贴）
    - 服务端追踪：API 调用模式（无法被客户端绕过）
    """

    # 需要追踪的 API 路径
    TRACKED_PATTERNS = [
        ("/api/ai/chat/", "AI_CHAT"),
        ("/api/sandbox/", "SANDBOX_ACCESS"),
        ("/api/events/", "EVENTS_UPLOAD"),
        ("/api/stages/submit/", "STAGE_SUBMIT_SERVER"),
        ("/api/submit/", "TASK_SUBMIT_SERVER"),
    ]

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        # 仅追踪候选人相关的 API
        path = request.url.path
        tracked_event = None
        for pattern, event_type in self.TRACKED_PATTERNS:
            if path.startswith(pattern):
                tracked_event = event_type
                break

        if tracked_event:
            # 从 URL 提取 token
            token = path.split("/")[-1]
            candidate = db.get_candidate_by_token(token)
            if candidate:
                try:
                    db.save_events([{
                        "candidate_id": candidate["id"],
                        "session_id": "server",
                        "timestamp": db.now_iso(),
                        "event_type": tracked_event,
                        "stage": 0,  # 服务端事件不区分阶段
                        "metadata": {
                            "method": request.method,
                            "path": path,
                            "status_code": response.status_code,
                            "source": "server_middleware",
                        }
                    }])
                except Exception:
                    pass  # 追踪失败不影响主流程

        return response


# 注册中间件（在 CORS 之后，路由之前）
app.add_middleware(BehaviorTrackingMiddleware)

if __name__ == "__main__":
    uvicorn.run("main:app", host=config.SERVER_HOST, port=config.SERVER_PORT, reload=True)
