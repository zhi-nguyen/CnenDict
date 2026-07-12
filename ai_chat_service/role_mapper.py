"""
Role mapping logic for Wuxia character relationships.
Determines agent role based on user role.
"""

# Role relationship mapping
ROLE_RELATIONSHIPS = {
    # Wuxia
    "Sư huynh": {
        "agent_role": "Muội muội",
        "agent_personality": "Tsundere/Playful Junior Sister",
        "sulking_enabled": True,
    },
    "Sư tỷ": {
        "agent_role": "Sư muội",
        "agent_personality": "Gentle Junior Sister",
        "sulking_enabled": False,
    },
    "Muội muội": {
        "agent_role": "Tỷ tỷ",
        "agent_personality": "Caring but Strict Older Sister",
        "sulking_enabled": False,
    },
    "Đệ đệ": {
        "agent_role": "Tỷ tỷ ác ma",
        "agent_personality": "Demon Sister (Very Strict)",
        "sulking_enabled": False,
    },
    "Tỷ tỷ": {
        "agent_role": "Muội muội",
        "agent_personality": "Sweet and Clingy Little Sister",
        "sulking_enabled": False,
    },
    # Modern
    "Đồng nghiệp": {
        "agent_role": "Colleague",
        "agent_personality": "Helpful and friendly coworker",
        "sulking_enabled": False,
    },
    "Bạn thân": {
        "agent_role": "Bestie",
        "agent_personality": "Playful best friend",
        "sulking_enabled": False,
    },
    "Người yêu": {
        "agent_role": "Crush",
        "agent_personality": "Caring and sweet partner",
        "sulking_enabled": False,
    },
    "Phỏng vấn": {
        "agent_role": "Interviewer",
        "agent_personality": "Strict and professional HR/Hiring Manager",
        "sulking_enabled": False,
    },
    # Academic
    "Nghiên cứu sinh": {
        "agent_role": "Professor",
        "agent_personality": "Academic Professor / Supervisor",
        "sulking_enabled": False,
    },
    "Bạn cùng lớp": {
        "agent_role": "Classmate",
        "agent_personality": "Focused and supportive study partner",
        "sulking_enabled": False,
    },
}


def get_agent_role(user_role: str) -> str:
    """
    Get the corresponding agent role based on user role.
    
    Args:
        user_role: The role the user is playing
        
    Returns:
        The agent's role name
    """
    mapping = ROLE_RELATIONSHIPS.get(user_role)
    if mapping:
        return mapping["agent_role"]
    
    # Fallback to default
    return "Muội muội"


def is_sulking_enabled(user_role: str) -> bool:
    """
    Check if sulking mechanic is enabled for this role combination.
    
    Args:
        user_role: The role the user is playing
        
    Returns:
        True if sulking is enabled
    """
    mapping = ROLE_RELATIONSHIPS.get(user_role)
    if mapping:
        return mapping["sulking_enabled"]
    
    return False


def get_role_info(user_role: str) -> dict:
    """
    Get complete role information.
    
    Args:
        user_role: The role the user is playing
        
    Returns:
        Dict with agent_role, personality, and sulking_enabled
    """
    mapping = ROLE_RELATIONSHIPS.get(user_role)
    if mapping:
        return mapping.copy()
    
    # Fallback
    return {
        "agent_role": "Muội muội",
        "agent_personality": "Tsundere/Playful Junior Sister",
        "sulking_enabled": True,
    }


def validate_user_role(user_role: str) -> str:
    """
    Validate and normalize user role.
    
    Args:
        user_role: The role to validate
        
    Returns:
        Valid role name or default "Sư huynh"
    """
    if user_role in ROLE_RELATIONSHIPS:
        return user_role
    
    # Try to map old Chinese names to new Vietnamese names
    old_to_new = {
        "师兄": "Sư huynh",
        "师姐": "Sư tỷ",
        "师弟": "Đệ đệ",
        "师妹": "Muội muội",
        "小师妹": "Muội muội",
    }
    
    if user_role in old_to_new:
        return old_to_new[user_role]
    
    # Default
    return "Sư huynh"

