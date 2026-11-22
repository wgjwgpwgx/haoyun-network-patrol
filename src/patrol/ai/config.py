"""AI 大模型分析配置

配置来源(优先级从高到低):
  1. 环境变量 PATROL_AI_* 
  2. config/ai.yaml
  3. 内置默认值

兼容所有 OpenAI Chat Completions 协议的服务:
DeepSeek、智谱 GLM、通义千问、Kimi、Ollama 本地模型等。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_DEFAULT_CONFIG_PATH = Path("config") / "ai.yaml"


@dataclass
class AIConfig:
    """AI 分析配置"""

    enabled: bool = False
    base_url: str = "https://api.deepseek.com/v1"
    api_key: str = ""
    model: str = "deepseek-chat"
    timeout: int = 120          # 请求超时(秒)
    max_tokens: int = 4096
    temperature: float = 0.2    # 分析任务用低温度保证稳定

    @property
    def ready(self) -> bool:
        """启用且配置了密钥才可调用。"""
        return self.enabled and bool(self.api_key.strip())


def load_ai_config(config_path: str | Path | None = None) -> AIConfig:
    """加载 AI 配置:yaml + 环境变量覆盖。"""
    cfg = AIConfig()

    path = Path(config_path) if config_path else _DEFAULT_CONFIG_PATH
    if path.exists():
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if isinstance(data, dict):
                for key in ("enabled", "base_url", "api_key", "model",
                            "timeout", "max_tokens", "temperature"):
                    if key in data and data[key] is not None:
                        setattr(cfg, key, data[key])
        except yaml.YAMLError as e:
            import logging
            logging.getLogger(__name__).warning("AI 配置文件解析失败 %s: %s", path, e)

    # 环境变量覆盖
    env = os.environ
    if env.get("PATROL_AI_ENABLED"):
        cfg.enabled = env["PATROL_AI_ENABLED"].lower() in ("1", "true", "yes", "on")
    if env.get("PATROL_AI_BASE_URL"):
        cfg.base_url = env["PATROL_AI_BASE_URL"]
    if env.get("PATROL_AI_API_KEY"):
        cfg.api_key = env["PATROL_AI_API_KEY"]
    if env.get("PATROL_AI_MODEL"):
        cfg.model = env["PATROL_AI_MODEL"]
    if env.get("PATROL_AI_TIMEOUT"):
        try:
            cfg.timeout = int(env["PATROL_AI_TIMEOUT"])
        except ValueError:
            pass

    return cfg
