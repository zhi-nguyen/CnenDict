"""
Text-to-Speech handler and utilities.
Contains Voice presets and text sanitization helpers.
No longer depends on edge-tts as audio is generated via Azure Speech Service.
"""

import logging
import re

logger = logging.getLogger(__name__)

def _sanitize_text_for_audio(text: str, learning_language: str = "zh") -> str:
    """
    Sanitize text for speech synthesis:
    1. Replace ellipses with commas to add natural pauses.
    2. For Chinese (zh), strip out Latin/Vietnamese words so the TTS engine only reads Chinese characters.
    """
    if not text:
        return ""
    
    # Replace triple dots or ellipsis characters with a comma for better voice rhythm
    comma_char = ',' if learning_language == 'en' else '，'
    cleaned_text = re.sub(r'(\.{2,}|…+)', comma_char, text)
    
    if learning_language == "zh":
        # Match one or more Latin/Vietnamese words (with common diacritics), optionally separated by spaces/hyphens
        latin_vi_pattern = r'[a-zA-ZáàảãạâấầẩẫậăắằẳẵặéèẻẽẹêếềểễệíìỉĩịóòỏõọôốồổỗộơớờởỡợúùủũụưứừửữựýỳỷỹỵđĐ]+(?:\s+[a-zA-ZáàảãạâấầẩẫậăắằẳẵặéèẻẽẹêếềểễệíìỉĩịóòỏõọôốồổỗộơớờởỡợúùủũụưứừửữựýỳỷỹỵđĐ]+)*'
        
        # Remove quoted Latin/Vietnamese strings: e.g. "xin chào" or “xin chào”
        cleaned_text = re.sub(r'["“\'‘]' + latin_vi_pattern + r'["”\'’]', '', cleaned_text)
        
        # Remove unquoted Latin/Vietnamese words
        cleaned_text = re.sub(latin_vi_pattern, '', cleaned_text)
        
        # Clean up empty quotes and extra spaces
        cleaned_text = re.sub(r'“”|""|\'\'|‘’', '', cleaned_text)
        cleaned_text = re.sub(r'\s+', ' ', cleaned_text).strip()
        
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

