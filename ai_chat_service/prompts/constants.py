"""
Configuration constants and options.
"""

EMOTION_OPTIONS = [
    "neutral",
    "happy",
    "excited",
    "cheerful",
    "strict",
    "concerned",
    "sulking",
    "angry"
]

ACTION_OPTIONS = [
    "none",
    "correction",
    "quiz"
]

MAX_HISTORY_TURNS = 20

REDIS_KEY_PATTERNS = {
    "conversation_history": "chat:history:{user_id}",
    "user_state": "chat:state:{user_id}",
    "sulking_level": "chat:sulking:{user_id}",
}
