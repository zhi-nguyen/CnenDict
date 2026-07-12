"""
System prompts and configurations for the Chinese & English Tutor AI Agent.
Stitches core system prompt and dynamic contexts (Wuxia, Modern, Academic).
"""

from typing import Optional
from .core import CORE_SYSTEM_PROMPT
from .wuxia import ROLE_PROTOCOLS_WUXIA, ROLE_EXAMPLES_WUXIA
from .modern import ROLE_PROTOCOLS_MODERN, ROLE_EXAMPLES_MODERN
from .academic import ROLE_PROTOCOLS_ACADEMIC, ROLE_EXAMPLES_ACADEMIC
from .constants import (
    EMOTION_OPTIONS,
    ACTION_OPTIONS,
    MAX_HISTORY_TURNS,
    REDIS_KEY_PATTERNS,
)

__all__ = [
    "CORE_SYSTEM_PROMPT",
    "EMOTION_OPTIONS",
    "ACTION_OPTIONS",
    "MAX_HISTORY_TURNS",
    "REDIS_KEY_PATTERNS",
    "get_system_instruction",
]


def get_system_instruction(
    agent_name: str,
    personality_desc: str,
    user_honorific_zh: str,
    agent_self_ref_zh: str,
    user_honorific_vi: str,
    agent_self_ref_vi: str,
    joy_current: float,
    sad_current: float,
    joy_sensitivity: float,
    sad_sensitivity: float,
    learning_language: str,
    context_setting: str,
    user_level: str,
    user_name: str,
    relation_type: str = "default",
) -> str:
    """
    Stitches core prompt and current context-specific (Wuxia, Modern, Academic)
    protocols and examples based on dynamic persona and language.
    """
    # 1. Format core system prompt
    system_instruction = CORE_SYSTEM_PROMPT.format(
        agent_name=agent_name,
        personality_desc=personality_desc,
        user_honorific_zh=user_honorific_zh,
        agent_self_ref_zh=agent_self_ref_zh,
        user_honorific_vi=user_honorific_vi,
        agent_self_ref_vi=agent_self_ref_vi,
        joy_current=joy_current,
        sad_current=sad_current,
        joy_sensitivity=joy_sensitivity,
        sad_sensitivity=sad_sensitivity,
        learning_language=learning_language,
        context_setting=context_setting,
        user_level=user_level,
        user_name=user_name,
    )
    
    # 2. Map role key for protocol loading
    role_key = ""
    if context_setting == "wuxia":
        wuxia_map = {
            "师兄": "Sư huynh",
            "师姐": "Sư tỷ",
            "师弟": "Đệ đệ",
            "师妹": "Muội muội",
            "徒儿": "Nữ Sư Phụ",
        }
        role_key = wuxia_map.get(user_honorific_zh, "Sư huynh")
    elif context_setting == "modern":
        modern_map = {
            "colleague": "Đồng nghiệp",
            "bestie": "Bạn thân",
            "crush": "Người yêu",
            "interviewer": "Phỏng vấn",
        }
        role_key = modern_map.get(relation_type, "Đồng nghiệp")
    elif context_setting == "academic":
        academic_map = {
            "professor": "Nghiên cứu sinh",
            "classmate": "Bạn cùng lớp",
        }
        role_key = academic_map.get(relation_type, "Nghiên cứu sinh")

    # 3. Extract protocol & examples based on context_setting and learning_language
    protocol = ""
    examples = ""
    
    if learning_language == "zh":
        if context_setting == "wuxia":
            protocol = ROLE_PROTOCOLS_WUXIA.get(role_key, ROLE_PROTOCOLS_WUXIA.get("Sư huynh", ""))
            examples = ROLE_EXAMPLES_WUXIA.get(role_key, ROLE_EXAMPLES_WUXIA.get("Sư huynh", ""))
        elif context_setting == "modern":
            protocol = ROLE_PROTOCOLS_MODERN["zh"].get(role_key, ROLE_PROTOCOLS_MODERN["zh"].get("Đồng nghiệp", ""))
            examples = ROLE_EXAMPLES_MODERN["zh"].get(role_key, ROLE_EXAMPLES_MODERN["zh"].get("Đồng nghiệp", ""))
        elif context_setting == "academic":
            protocol = ROLE_PROTOCOLS_ACADEMIC["zh"].get(role_key, ROLE_PROTOCOLS_ACADEMIC["zh"].get("Nghiên cứu sinh", ""))
            examples = ROLE_EXAMPLES_ACADEMIC["zh"].get(role_key, ROLE_EXAMPLES_ACADEMIC["zh"].get("Nghiên cứu sinh", ""))
    elif learning_language == "en":
        # Force modern or academic (wuxia not supported for English)
        actual_context = "modern" if context_setting == "wuxia" else context_setting
        if actual_context == "modern":
            protocol = ROLE_PROTOCOLS_MODERN["en"].get(role_key, ROLE_PROTOCOLS_MODERN["en"].get("Đồng nghiệp", ""))
            examples = ROLE_EXAMPLES_MODERN["en"].get(role_key, ROLE_EXAMPLES_MODERN["en"].get("Đồng nghiệp", ""))
        elif actual_context == "academic":
            protocol = ROLE_PROTOCOLS_ACADEMIC["en"].get(role_key, ROLE_PROTOCOLS_ACADEMIC["en"].get("Nghiên cứu sinh", ""))
            examples = ROLE_EXAMPLES_ACADEMIC["en"].get(role_key, ROLE_EXAMPLES_ACADEMIC["en"].get("Nghiên cứu sinh", ""))
            
    # 4. Stitch together
    if protocol:
        formatted_protocol = protocol.format(
            user_role=role_key,
            agent_role=agent_name,
            sulking_level=0  # Sulking level is deprecating in favor of dynamic joy/sad floats
        )
        system_instruction += f"\n\n{formatted_protocol}"
        
    if examples:
        system_instruction += f"\n\n{examples}"
        
    return system_instruction
