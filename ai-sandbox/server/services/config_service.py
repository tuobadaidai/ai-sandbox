# AI 沙盒行为洞察系统 - 统一配置管理服务
# 读取优先级：config_store.json > 环境变量 > 代码默认值
# 写入方式：API 写入 config_store.json + 热更新内存缓存
# 线程安全：读写锁保护

import json
import copy
import threading
from pathlib import Path
from typing import Any, Optional
from datetime import datetime


class ConfigService:
    """统一配置管理服务（单例模式）"""

    _instance = None
    _init_lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._init_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, config_path: Path = None):
        if hasattr(self, '_initialized'):
            return
        self._initialized = True
        self._lock = threading.RLock()
        self.config_path = config_path or Path(__file__).parent.parent / "data" / "config_store.json"
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache = self._load()
        # 初始化默认结构
        self._ensure_defaults()

    def _ensure_defaults(self):
        """确保配置结构完整，缺失字段用默认值填充"""
        defaults = {
            "version": 1,
            "ai": {
                "provider": None,  # 运行时根据 API Key 自动判断
                "dashscope": {
                    "api_key": "",
                    "model": "qwen-plus",
                    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"
                },
                "ollama": {
                    "api_key": "ollama",
                    "model": "qwen2:1.5b",
                    "base_url": "http://localhost:11434/v1"
                },
                "params": {
                    "max_tokens": 2048,
                    "temperature": 0.7,
                    "timeout": 60
                },
                "hallucination_rate": 0.15
            },
            "task": {
                "active_task": "task_v3_valid.json"
            },
            "evaluation": {
                "dimension_weights": {
                    "ai_fluency": 0.15,
                    "human_ai_judgment": 0.25,
                    "architecture_design": 0.20,
                    "hybrid_orchestration": 0.15,
                    "cognitive_depth": 0.15,
                    "problem_modeling": 0.10
                },
                "level_thresholds": {
                    "L1": 1.8,
                    "L2": 2.5,
                    "L3": 3.2
                },
                "score_range": {
                    "min": 1.0,
                    "max": 4.0
                },
                "keywords": {
                    "decomposition": ["首先", "第一步", "框架", "拆解", "分", "步骤", "方案", "结构"],
                    "clarification": ["?", "？", "什么", "哪些", "如何", "怎么", "是否", "请确认", "确认一下"],
                    "verification": ["验证", "检查", "确认", "数据", "来源", "准确", "真实", "核实", "查证"]
                }
            }
        }

        def deep_merge(base, override):
            """深层合并：override 覆盖 base，base 补充 override 缺失的键"""
            result = copy.deepcopy(base)
            for k, v in override.items():
                if k in result and isinstance(result[k], dict) and isinstance(v, dict):
                    result[k] = deep_merge(result[k], v)
                else:
                    result[k] = v
            return result

        self._cache = deep_merge(defaults, self._cache)
        self._save()

    def _load(self) -> dict:
        """从 JSON 文件加载配置"""
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return {}
        return {}

    def _save(self):
        """持久化到 JSON 文件（原子写入）"""
        self._cache["updated_at"] = datetime.now().isoformat()
        tmp = self.config_path.with_suffix('.tmp')
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(self._cache, f, ensure_ascii=False, indent=2)
        tmp.rename(self.config_path)

    def get(self, category: str, key: str = None, default: Any = None) -> Any:
        """读取配置（线程安全）"""
        with self._lock:
            section = self._cache.get(category, {})
            if key is None:
                return copy.deepcopy(section)
            return copy.deepcopy(section.get(key, default))

    def get_all(self) -> dict:
        """获取全部配置（脱敏版）"""
        with self._lock:
            return self.mask_sensitive(copy.deepcopy(self._cache))

    def set(self, category: str, key: str, value: Any, operator: str = "admin"):
        """写入单个配置（线程安全 + 热更新 + 审计日志）"""
        with self._lock:
            old_value = self._cache.get(category, {}).get(key)
            if category not in self._cache:
                self._cache[category] = {}
            self._cache[category][key] = value
            self._save()
            self._log_change(category, key, old_value, value, operator)
            self._apply_hot_reload(category, key, value)

    def set_batch(self, category: str, updates: dict, operator: str = "admin"):
        """批量更新某个分类下的配置"""
        with self._lock:
            if category not in self._cache:
                self._cache[category] = {}
            for key, value in updates.items():
                old_value = self._cache[category].get(key)
                self._cache[category][key] = value
                self._log_change(category, key, old_value, value, operator)
            self._save()
            # 批量热更新
            for key, value in updates.items():
                self._apply_hot_reload(category, key, value)

    def _apply_hot_reload(self, category: str, key: str, value: Any):
        """热更新：修改内存中的运行时配置"""
        try:
            if category == "ai":
                from services.ai_provider import update_runtime_config
                update_runtime_config(key, value)
            elif category == "evaluation":
                from services.behavior_analyzer import update_evaluation_config
                update_evaluation_config(key, value)
            elif category == "task":
                import config
                if key == "active_task":
                    config.DEFAULT_TASK = value
        except Exception:
            pass  # 热更新失败不阻塞主流程

    def _log_change(self, category: str, key: str, old_value: Any, new_value: Any, operator: str):
        """记录配置变更到数据库"""
        import database as db

        def mask_val(v, k):
            """敏感字段脱敏"""
            if isinstance(v, str) and any(s in k.lower() for s in ('key', 'secret', 'password', 'token')):
                return v[:4] + '***' + v[-4:] if len(v) > 8 else '***'
            return v

        with db.db_conn() as conn:
            conn.execute(
                "INSERT INTO config_changelog (category, `key`, old_value, new_value, operator, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (category, key,
                 json.dumps(mask_val(old_value, key), ensure_ascii=False) if old_value is not None else None,
                 json.dumps(mask_val(new_value, key), ensure_ascii=False) if new_value is not None else None,
                 operator, db.now_iso())
            )
            conn.commit()

    def get_changelog(self, category: str = None, limit: int = 50) -> list:
        """获取配置变更历史"""
        import database as db
        with db.db_conn() as conn:
            if category:
                rows = conn.execute(
                    "SELECT * FROM config_changelog WHERE category = ? ORDER BY created_at DESC LIMIT ?",
                    (category, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM config_changelog ORDER BY created_at DESC LIMIT ?",
                    (limit,)
                ).fetchall()
            return [dict(r) for r in rows]

    @staticmethod
    def mask_sensitive(config: dict) -> dict:
        """脱敏配置中的敏感字段"""
        result = copy.deepcopy(config)
        sensitive_keys = {'api_key', 'secret', 'password', 'token'}

        def mask_dict(d):
            for k, v in d.items():
                if isinstance(v, dict):
                    mask_dict(v)
                elif isinstance(v, str) and k in sensitive_keys and v:
                    d[k] = v[:4] + '***' + v[-4:] if len(v) > 8 else '***'
        mask_dict(result)
        return result

    def reset_category(self, category: str, operator: str = "admin"):
        """重置某个分类为默认值"""
        defaults = {
            "evaluation": {
                "dimension_weights": {
                    "ai_fluency": 0.15,
                    "human_ai_judgment": 0.25,
                    "architecture_design": 0.20,
                    "hybrid_orchestration": 0.15,
                    "cognitive_depth": 0.15,
                    "problem_modeling": 0.10
                },
                "level_thresholds": {"L1": 1.8, "L2": 2.5, "L3": 3.2},
                "score_range": {"min": 1.0, "max": 4.0},
                "keywords": {
                    "decomposition": ["首先", "第一步", "框架", "拆解", "分", "步骤", "方案", "结构"],
                    "clarification": ["?", "？", "什么", "哪些", "如何", "怎么", "是否", "请确认", "确认一下"],
                    "verification": ["验证", "检查", "确认", "数据", "来源", "准确", "真实", "核实", "查证"]
                }
            }
        }
        if category in defaults:
            self.set_batch(category, defaults[category], operator)
