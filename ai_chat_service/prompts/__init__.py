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
    user_role: str,
    agent_role: str,
    sulking_level: int = 0,
    user_level: str = "Beginner",
    topic: str = "Daily Conversation",
    user_name: Optional[str] = None,
    learning_language: str = "zh",
    context_setting: str = "wuxia",
) -> str:
    """
    Stitches core prompt and current context-specific (Wuxia, Modern, Academic)
    protocols and examples based on language.
    """
    # 1. Format core system prompt
    system_instruction = CORE_SYSTEM_PROMPT.format(
        learning_language=learning_language,
        context_setting=context_setting,
        user_role=user_role,
        agent_role=agent_role,
        sulking_level=sulking_level,
        user_level=user_level,
        topic=topic,
        user_name=user_name if user_name else user_role,
    )
    
    # 2. Extract protocol & examples based on context_setting and learning_language
    protocol = ""
    examples = ""
    
    if learning_language == "zh":
        if context_setting == "wuxia":
            protocol = ROLE_PROTOCOLS_WUXIA.get(user_role, ROLE_PROTOCOLS_WUXIA.get("Sư huynh", ""))
            examples = ROLE_EXAMPLES_WUXIA.get(user_role, ROLE_EXAMPLES_WUXIA.get("Sư huynh", ""))
        elif context_setting == "modern":
            protocol = ROLE_PROTOCOLS_MODERN["zh"].get(user_role, ROLE_PROTOCOLS_MODERN["zh"].get("Đồng nghiệp", ""))
            examples = ROLE_EXAMPLES_MODERN["zh"].get(user_role, ROLE_EXAMPLES_MODERN["zh"].get("Đồng nghiệp", ""))
        elif context_setting == "academic":
            protocol = ROLE_PROTOCOLS_ACADEMIC["zh"].get(user_role, ROLE_PROTOCOLS_ACADEMIC["zh"].get("Nghiên cứu sinh", ""))
            examples = ROLE_EXAMPLES_ACADEMIC["zh"].get(user_role, ROLE_EXAMPLES_ACADEMIC["zh"].get("Nghiên cứu sinh", ""))
    elif learning_language == "en":
        # Force modern or academic (wuxia not supported for English)
        actual_context = "modern" if context_setting == "wuxia" else context_setting
        if actual_context == "modern":
            protocol = ROLE_PROTOCOLS_MODERN["en"].get(user_role, ROLE_PROTOCOLS_MODERN["en"].get("Đồng nghiệp", ""))
            examples = ROLE_EXAMPLES_MODERN["en"].get(user_role, ROLE_EXAMPLES_MODERN["en"].get("Đồng nghiệp", ""))
        elif actual_context == "academic":
            protocol = ROLE_PROTOCOLS_ACADEMIC["en"].get(user_role, ROLE_PROTOCOLS_ACADEMIC["en"].get("Nghiên cứu sinh", ""))
            examples = ROLE_EXAMPLES_ACADEMIC["en"].get(user_role, ROLE_EXAMPLES_ACADEMIC["en"].get("Nghiên cứu sinh", ""))
            
    # 3. Stitch together
    if protocol:
        formatted_protocol = protocol.format(
            user_role=user_role,
            agent_role=agent_role,
            sulking_level=sulking_level
        )
        system_instruction += f"\n\n{formatted_protocol}"
        
    if examples:
        system_instruction += f"\n\n{examples}"
        
    return system_instruction
