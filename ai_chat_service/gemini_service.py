"""
Legacy module - Gemini service has been moved to ai_agent.py

This file is kept for backward compatibility.
Please use:
    from apps.xiaoyue.services.ai_agent import ChineseTutorAgent

For TTS functionality, use:
    from apps.xiaoyue.services.tts_handler import generate_tts_audio

For Redis operations, use:
    from apps.xiaoyue.services.redis_client import RedisClient
"""

# Re-export for backward compatibility
from .ai_agent import ChineseTutorAgent
from .tts_handler import generate_tts_audio, generate_tts_with_emotion
from .redis_client import RedisClient

__all__ = [
    "ChineseTutorAgent",
    "generate_tts_audio",
    "generate_tts_with_emotion",
    "RedisClient"
]

