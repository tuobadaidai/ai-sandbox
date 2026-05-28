# AI 沙盒行为洞察系统 数据库操作
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Optional

from config import DATABASE_PATH, ADMIN_SECRET


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
            candidate_id TEXT UNIQUE NOT NULL,
            narrative_text TEXT DEFAULT '',
            dimension_scores TEXT DEFAULT '{}',
            contradictions TEXT DEFAULT '[]',
            cognitive_profile TEXT DEFAULT '{}',
            average_score REAL DEFAULT 0,
            comprehensive_score REAL DEFAULT 0,
            level TEXT DEFAULT '',
            confidence TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (candidate_id) REFERENCES candidates(id)
        );

        CREATE INDEX IF NOT EXISTS idx_events_candidate ON behavior_events(candidate_id);
        CREATE INDEX IF NOT EXISTS idx_events_stage ON behavior_events(candidate_id, stage);
        CREATE INDEX IF NOT EXISTS idx_ai_candidate ON ai_interactions(candidate_id);
    """)
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

def save_evaluation(candidate_id: str, narrative: str, dimension_scores: dict,
                    contradictions: list, cognitive_profile: dict, average_score: float,
                    comprehensive_score: float, level: str, confidence: str):
    conn = get_connection()
    try:
        conn.execute(
            """INSERT OR REPLACE INTO evaluations
               (candidate_id, narrative_text, dimension_scores, contradictions, cognitive_profile,
                average_score, comprehensive_score, level, confidence, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (candidate_id, narrative,
             json.dumps(dimension_scores, ensure_ascii=False),
             json.dumps(contradictions, ensure_ascii=False),
             json.dumps(cognitive_profile, ensure_ascii=False),
             average_score, comprehensive_score, level, confidence, now_iso())
        )
        conn.commit()
        update_candidate_status(candidate_id, "evaluated")
    finally:
        conn.close()


def get_evaluation(candidate_id: str) -> Optional[dict]:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM evaluations WHERE candidate_id = ?", (candidate_id,)
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["dimension_scores"] = json.loads(d["dimension_scores"])
        d["contradictions"] = json.loads(d["contradictions"])
        d["cognitive_profile"] = json.loads(d["cognitive_profile"])
        return d
    finally:
        conn.close()


def verify_admin(secret: str) -> bool:
    return secret == ADMIN_SECRET
