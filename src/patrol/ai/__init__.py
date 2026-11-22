"""AI 大模型分析模块

对外主入口:
  from patrol.ai import analyze_report, load_ai_config, AINotConfigured
"""
from patrol.ai.analyzer import AINotConfigured, analyze_report, risk_label_cn
from patrol.ai.client import LLMClient, LLMError
from patrol.ai.config import AIConfig, load_ai_config

__all__ = [
    "AIConfig",
    "AINotConfigured",
    "LLMClient",
    "LLMError",
    "analyze_report",
    "load_ai_config",
    "risk_label_cn",
]
