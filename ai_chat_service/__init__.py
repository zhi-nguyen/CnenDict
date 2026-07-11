"""
Services package for XiaoYue chatbot.
Contains AI agent, TTS handler, Redis client, and role mapper.
"""

from .ai_agent import ChineseTutorAgent
from .tts_handler import generate_tts_audio
from .redis_client import RedisClient
from .role_mapper import get_agent_role, validate_user_role, is_sulking_enabled

__all__ = [
    "ChineseTutorAgent",
    "generate_tts_audio",
    "RedisClient",
    "get_agent_role",
    "validate_user_role",
    "is_sulking_enabled",
]

