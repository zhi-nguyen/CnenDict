"""
Text-to-Speech handler and utilities.
Contains Voice presets and text sanitization helpers.
No longer depends on edge-tts as audio is generated via Azure Speech Service.
"""

import logging
import re

logger = logging.getLogger(__name__)

def _sanitize_text_for_audio(text: str) -> str:
    """
    Sanitize text for speech synthesis: replace ellipses with commas to add natural pauses.
    """
    if not text:
        return ""
    
    # Replace triple dots or ellipsis characters with a comma for better voice rhythm
    cleaned_text = re.sub(r'(\.{2,}|…+)', '，', text)
    return cleaned_text


# Voice presets for Chinese (zh-CN-XiaoxiaoNeural)
VOICE_PRESETS = {
    "neutral": {"voice": "zh-CN-XiaoxiaoNeural", "rate": "+0%", "volume": "+0%"},
    "happy": {"voice": "zh-CN-XiaoxiaoNeural", "rate": "+10%", "volume": "+10%"},
    "excited": {"voice": "zh-CN-XiaoxiaoNeural", "rate": "+15%", "volume": "+20%"},
    "cheerful": {"voice": "zh-CN-XiaoxiaoNeural", "rate": "+10%", "volume": "+10%"},
    "strict": {"voice": "zh-CN-XiaoxiaoNeural", "rate": "-5%", "volume": "+10%"},
    "concerned": {"voice": "zh-CN-XiaoxiaoNeural", "rate": "-5%", "volume": "-15%"},
    "sulking": {"voice": "zh-CN-XiaoxiaoNeural", "rate": "-10%", "volume": "-10%"},
    "angry": {"voice": "zh-CN-XiaoxiaoNeural", "rate": "+20%", "volume": "+25%"}
}

# Voice presets for English (en-US-JennyNeural)
VOICE_PRESETS_EN = {
    "neutral": {"voice": "en-US-JennyNeural", "rate": "+0%", "volume": "+0%"},
    "happy": {"voice": "en-US-JennyNeural", "rate": "+5%", "volume": "+5%"},
    "excited": {"voice": "en-US-JennyNeural", "rate": "+10%", "volume": "+10%"},
    "cheerful": {"voice": "en-US-JennyNeural", "rate": "+5%", "volume": "+5%"},
    "strict": {"voice": "en-US-JennyNeural", "rate": "-2%", "volume": "+5%"},
    "concerned": {"voice": "en-US-JennyNeural", "rate": "-2%", "volume": "-10%"},
    "sulking": {"voice": "en-US-JennyNeural", "rate": "-5%", "volume": "-5%"},
    "angry": {"voice": "en-US-JennyNeural", "rate": "+10%", "volume": "+15%"}
}

def get_voice_presets(learning_language: str = "zh") -> dict:
    """Get the appropriate voice presets dictionary based on learning language."""
    if learning_language == "en":
        return VOICE_PRESETS_EN
    return VOICE_PRESETS

