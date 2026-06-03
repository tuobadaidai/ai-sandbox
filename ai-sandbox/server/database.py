# AI 沙盒行为洞察系统 数据库操作
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Optional

import hashlib
import hmac
import secrets
import time

from config import DATABASE_PATH, ADMIN_SECRET, ADMIN_SESSION_EXPIRY


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DATABASE_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """初始化数据库表结构"""
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS candidates (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT,
            token TEXT UNIQUE NOT NULL,
            created_at TEXT NOT NULL,
            status TEXT DEFAULT 'pending'
        );

        CREATE TABLE IF NOT EXISTS behavior_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            event_type TEXT NOT NULL,
            stage INTEGER NOT NULL,
            metadata TEXT DEFAULT '{}',
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (candidate_id) REFERENCES candidates(id)
        );

        CREATE TABLE IF NOT EXISTS ai_interactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_id TEXT NOT NULL,
            stage INTEGER NOT NULL,
            prompt TEXT NOT NULL,
            response TEXT NOT NULL,
            prompt_length INTEGER DEFAULT 0,
            response_length INTEGER DEFAULT 0,
            response_time_ms INTEGER DEFAULT 0,
            contains_hallucination INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (candidate_id) REFERENCES candidates(id)
        );

        CREATE TABLE IF NOT EXISTS evaluations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_id TEXT NOT NULL,
            version INTEGER DEFAULT 1,
            narrative_text TEXT DEFAULT '',
            dimension_scores TEXT DEFAULT '{}',
            contradictions TEXT DEFAULT '[]',
            cognitive_profile TEXT DEFAULT '{}',
            average_score REAL DEFAULT 0,
            comprehensive_score REAL DEFAULT 0,
            level TEXT DEFAULT '',
            confidence TEXT DEFAULT '',
            new_dimension_scores TEXT DEFAULT '{}',
            collaboration_style TEXT DEFAULT '',
            cmmi_maturity_level TEXT DEFAULT '',
            work_dna_portrait TEXT DEFAULT '',
            algorithm_version TEXT DEFAULT 'v1',
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (candidate_id) REFERENCES candidates(id)
        );

        CREATE INDEX IF NOT EXISTS idx_eval_candidate ON evaluations(candidate_id);

        CREATE TABLE IF NOT EXISTS stage_submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_id TEXT NOT NULL,
            stage INTEGER NOT NULL,
            content TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (candidate_id) REFERENCES candidates(id),
            UNIQUE(candidate_id, stage)
        );

        CREATE INDEX IF NOT EXISTS idx_events_candidate ON behavior_events(candidate_id);
        CREATE INDEX IF NOT EXISTS idx_events_stage ON behavior_events(candidate_id, stage);
        CREATE INDEX IF NOT EXISTS idx_ai_candidate ON ai_interactions(candidate_id);

        CREATE TABLE IF NOT EXISTS admin_sessions (
            session_id TEXT PRIMARY KEY,
            expires_at TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );
    """)
    # Migration: add new columns if upgrading from older schema
    try:
        conn.execute("ALTER TABLE evaluations ADD COLUMN work_dna_portrait TEXT DEFAULT ''")
    except Exception:
        pass
    # 清理过期管理员会话
    try:
        conn.execute("DELETE FROM admin_sessions WHERE expires_at < ?", (str(int(time.time())),))
    except Exception:
        pass
    conn.commit()
    conn.close()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# === 候选人 CRUD ===

def create_candidate(name: str, email: Optional[str], token: str, candidate_id: str) -> dict:
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO candidates (id, name, email, token, created_at, status) VALUES (?, ?, ?, ?, ?, ?)",
            (candidate_id, name, email, token, now_iso(), "pending")
        )
        conn.commit()
        return get_candidate_by_token(token)
    finally:
        conn.close()


def get_candidate_by_token(token: str) -> Optional[dict]:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM candidates WHERE token = ?", (token,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_candidate_by_id(candidate_id: str) -> Optional[dict]:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM candidates WHERE id = ?", (candidate_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def update_candidate_status(candidate_id: str, status: str):
    conn = get_connection()
    try:
        conn.execute("UPDATE candidates SET status = ? WHERE id = ?", (status, candidate_id))
        conn.commit()
    finally:
        conn.close()


def list_candidates() -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM candidates ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# === 行为事件 ===

def save_events(events: list[dict]):
    """批量保存行为事件"""
    if not events:
        return
    conn = get_connection()
    try:
        conn.executemany(
            "INSERT INTO behavior_events (candidate_id, session_id, timestamp, event_type, stage, metadata) VALUES (?, ?, ?, ?, ?, ?)",
            [
                (e["candidate_id"], e["session_id"], e["timestamp"],
                 e["event_type"], e["stage"], json.dumps(e.get("metadata", {}), ensure_ascii=False))
                for e in events
            ]
        )
        conn.commit()
    finally:
        conn.close()


def get_events(candidate_id: str) -> list[dict]:
    """获取候选人的所有行为事件"""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM behavior_events WHERE candidate_id = ? ORDER BY timestamp ASC",
            (candidate_id,)
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["metadata"] = json.loads(d["metadata"])
            result.append(d)
        return result
    finally:
        conn.close()


def get_events_by_stage(candidate_id: str, stage: int) -> list[dict]:
    """获取候选人某阶段的行为事件"""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM behavior_events WHERE candidate_id = ? AND stage = ? ORDER BY timestamp ASC",
            (candidate_id, stage)
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["metadata"] = json.loads(d["metadata"])
            result.append(d)
        return result
    finally:
        conn.close()


# === AI 交互 ===

def save_ai_interaction(candidate_id: str, stage: int, prompt: str, response: str,
                       prompt_length: int, response_length: int, response_time_ms: int,
                       contains_hallucination: bool):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO ai_interactions (candidate_id, stage, prompt, response, prompt_length, response_length, response_time_ms, contains_hallucination, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (candidate_id, stage, prompt, response, prompt_length, response_length,
             response_time_ms, int(contains_hallucination), now_iso())
        )
        conn.commit()
    finally:
        conn.close()


def get_ai_interactions(candidate_id: str) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM ai_interactions WHERE candidate_id = ? ORDER BY created_at ASC",
            (candidate_id,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# === 评估结果 ===

ALGORITHM_VERSION = "v3-exec-assessment"  # 当前算法版本


def save_evaluation(candidate_id: str, narrative: str, dimension_scores: dict,
                    contradictions: list, cognitive_profile: dict, average_score: float,
                    comprehensive_score: float, level: str, confidence: str,
                    new_dimension_scores: dict = None, collaboration_style: str = None,
                    cmmi_maturity_level: str = None, work_dna_portrait: str = None):
    conn = get_connection()
    try:
        # 计算版本号：该候选人的已有评估数 + 1
        existing = conn.execute(
            "SELECT COUNT(*) as cnt FROM evaluations WHERE candidate_id = ?",
            (candidate_id,)
        ).fetchone()
        version = (existing["cnt"] if existing else 0) + 1

        conn.execute(
            """INSERT INTO evaluations
            (candidate_id, version, narrative_text, dimension_scores, contradictions, cognitive_profile,
             average_score, comprehensive_score, level, confidence, new_dimension_scores,
             collaboration_style, cmmi_maturity_level, work_dna_portrait, algorithm_version, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (candidate_id, version, narrative, json.dumps(dimension_scores, ensure_ascii=False),
             json.dumps(contradictions, ensure_ascii=False), json.dumps(cognitive_profile, ensure_ascii=False),
             average_score, comprehensive_score, level, confidence,
             json.dumps(new_dimension_scores, ensure_ascii=False) if new_dimension_scores else None,
             collaboration_style, cmmi_maturity_level, work_dna_portrait,
             ALGORITHM_VERSION, now_iso())
        )
        conn.commit()
        update_candidate_status(candidate_id, "evaluated")
    finally:
        conn.close()


def get_evaluation(candidate_id: str, version: int = None) -> Optional[dict]:
    """获取候选人评估结果，默认返回最新版本。指定 version 可获取历史版本。"""
    conn = get_connection()
    try:
        if version:
            row = conn.execute(
                "SELECT * FROM evaluations WHERE candidate_id = ? AND version = ?",
                (candidate_id, version)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM evaluations WHERE candidate_id = ? ORDER BY version DESC LIMIT 1",
                (candidate_id,)
            ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["dimension_scores"] = json.loads(d["dimension_scores"])
        d["contradictions"] = json.loads(d["contradictions"])
        d["cognitive_profile"] = json.loads(d["cognitive_profile"])
        if d.get("new_dimension_scores"):
            d["new_dimension_scores"] = json.loads(d["new_dimension_scores"])
        return d
    finally:
        conn.close()


def get_evaluation_versions(candidate_id: str) -> list[dict]:
    """获取候选人所有评估版本的摘要列表"""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, version, average_score, comprehensive_score, level, algorithm_version, created_at FROM evaluations WHERE candidate_id = ? ORDER BY version DESC",
            (candidate_id,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def save_stage_submission(candidate_id: str, stage: int, content: str):
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO stage_submissions (candidate_id, stage, content, created_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(candidate_id, stage) 
               DO UPDATE SET content=excluded.content, created_at=excluded.created_at""",
            (candidate_id, stage, content, now_iso())
        )
        conn.commit()
    finally:
        conn.close()


def get_stage_submission(candidate_id: str, stage: int) -> Optional[dict]:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM stage_submissions WHERE candidate_id = ? AND stage = ?",
            (candidate_id, stage)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_all_stage_submissions(candidate_id: str) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM stage_submissions WHERE candidate_id = ? ORDER BY stage",
            (candidate_id,)
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def verify_admin(secret: str) -> bool:
    """时序安全的密码比较，防止计时攻击"""
    if not ADMIN_SECRET or not secret:
        return False
    return hmac.compare_digest(secret, ADMIN_SECRET)


# === 管理员会话 ===

def create_admin_session() -> str:
    """创建管理员会话 token，返回 session_id"""
    session_id = f"admin_{secrets.token_hex(16)}"
    expires_at = str(int(time.time()) + ADMIN_SESSION_EXPIRY)
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO admin_sessions (session_id, expires_at) VALUES (?, ?)",
            (session_id, expires_at)
        )
        conn.commit()
    finally:
        conn.close()
    return session_id


def verify_admin_session(session_id: str) -> bool:
    """验证管理员会话是否有效且未过期"""
    if not session_id:
        return False
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT expires_at FROM admin_sessions WHERE session_id = ?",
            (session_id,)
        ).fetchone()
        if not row:
            return False
        expires_at = int(row["expires_at"])
        if time.time() > expires_at:
            # 清理过期会话
            conn.execute("DELETE FROM admin_sessions WHERE session_id = ?", (session_id,))
            conn.commit()
            return False
        return True
    finally:
        conn.close()


def cleanup_expired_sessions():
    """清理所有过期会话"""
    conn = get_connection()
    try:
        conn.execute(
            "DELETE FROM admin_sessions WHERE expires_at < ?",
            (str(int(time.time())),)
        )
        conn.commit()
    finally:
        conn.close()
