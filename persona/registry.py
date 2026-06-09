"""Persona 人物注册表 — 加载和管理 Persona Profile YAML 文件。

Usage:
    from persona.registry import PERSONA_MAP, load_persona, list_personas
    profile = load_persona("ecommerce_buyer")
"""

import yaml
from pathlib import Path
from loguru import logger

_PERSONA_DIR = Path(__file__).parent / "personas"


def _load_all() -> dict:
    """加载所有 Persona Profile YAML 文件。"""
    profiles = {}
    if not _PERSONA_DIR.exists():
        logger.warning(f"Persona 目录不存在: {_PERSONA_DIR}")
        return profiles

    for yaml_file in _PERSONA_DIR.glob("*.yaml"):
        try:
            with open(yaml_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if data and data.get("name"):
                profiles[data["name"]] = data
                logger.debug(f"已加载 Persona: {data['name']}")
            else:
                logger.warning(f"无效 Persona 文件: {yaml_file}")
        except Exception as exc:
            logger.warning(f"加载 Persona 失败 ({yaml_file}): {exc}")

    return profiles


PERSONA_MAP = _load_all()


def load_persona(name: str) -> dict:
    """加载指定名称的 Persona Profile。

    Raises:
        ValueError: Persona 不存在
    """
    if name not in PERSONA_MAP:
        available = ", ".join(PERSONA_MAP.keys())
        raise ValueError(f"Unknown persona '{name}'. Available: {available}")
    return PERSONA_MAP[name]


def list_personas() -> list[str]:
    """返回所有可用的人物名称。"""
    return list(PERSONA_MAP.keys())


def reload_personas():
    """热重载所有 Persona Profile（开发时使用）。"""
    global PERSONA_MAP
    PERSONA_MAP = _load_all()
    logger.info(f"已重载 {len(PERSONA_MAP)} 个 Persona")
