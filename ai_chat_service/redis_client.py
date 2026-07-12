"""
Redis client for managing conversation history and user state.
"""

import json
import logging
from typing import Any, Dict, List, Optional
from redis import asyncio as aioredis
from config import settings

logger = logging.getLogger(__name__)


class RedisClient:
    """
    Async Redis client for managing user conversations and state.
    """
    
    def __init__(self):
        self.redis_url = settings.REDIS_URL
        logger.info(f"Connecting to Redis at: {self.redis_url}")
        self._client: Optional[aioredis.Redis] = None
    
    async def get_client(self) -> aioredis.Redis:
        """Get or create Redis client connection."""
        if self._client is None:
            self._client = await aioredis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True
            )
        return self._client
    
    async def close(self):
        """Close Redis connection."""
        if self._client:
            await self._client.close()
            self._client = None
    
    # ==================== Conversation History ====================
    
    async def get_conversation_history(
        self, 
        user_id: str, 
        limit: int = 20,
        persona_id: str = None
    ) -> List[Dict[str, Any]]:
        """
        Retrieve conversation history for a user.
        
        Args:
            user_id: Unique user identifier
            limit: Maximum number of messages to retrieve
            persona_id: Optional tutor persona identifier
            
        Returns:
            List of conversation turns (oldest to newest)
        """
        client = await self.get_client()
        key = f"chat:history:{user_id}:{persona_id}" if persona_id else f"chat:history:{user_id}"
        
        try:
            # Get last N messages from the list
            messages = await client.lrange(key, -limit, -1)
            return [json.loads(msg) for msg in messages]
        except Exception as e:
            logger.error(f"Error retrieving conversation history: {e}")
            return []
    
    async def add_to_conversation_history(
        self, 
        user_id: str, 
        message: Dict[str, Any],
        max_history: int = 100,
        persona_id: str = None
    ) -> bool:
        """
        Add a message to conversation history.
        
        Args:
            user_id: Unique user identifier
            message: Message dict with keys like 'role', 'content', 'timestamp'
            max_history: Maximum messages to keep in history
            persona_id: Optional tutor persona identifier
            
        Returns:
            True if successful
        """
        client = await self.get_client()
        key = f"chat:history:{user_id}:{persona_id}" if persona_id else f"chat:history:{user_id}"
        
        try:
            # Add message to the right of the list
            await client.rpush(key, json.dumps(message, ensure_ascii=False))
            
            # Trim to keep only last max_history messages
            await client.ltrim(key, -max_history, -1)
            
            # Set expiration (30 days)
            await client.expire(key, 30 * 24 * 60 * 60)
            
            return True
        except Exception as e:
            logger.error(f"Error adding to conversation history: {e}")
            return False
    
    async def clear_conversation_history(self, user_id: str, persona_id: str = None) -> bool:
        """Clear all conversation history for a user and persona."""
        client = await self.get_client()
        key = f"chat:history:{user_id}:{persona_id}" if persona_id else f"chat:history:{user_id}"
        
        try:
            await client.delete(key)
            return True
        except Exception as e:
            logger.error(f"Error clearing conversation history: {e}")
            return False
    
    # ==================== User State Management ====================
    
    async def get_sulking_level(self, user_id: str, persona_id: str = None) -> int:
        """
        Get the current sulking level for a user and persona.
        
        Args:
            user_id: Unique user identifier
            persona_id: Optional tutor persona identifier
            
        Returns:
            Sulking level (0-3), defaults to 0
        """
        client = await self.get_client()
        key = f"chat:sulking:{user_id}:{persona_id}" if persona_id else f"chat:sulking:{user_id}"
        
        try:
            level = await client.get(key)
            return int(level) if level else 0
        except Exception as e:
            logger.error(f"Error getting sulking level: {e}")
            return 0
    
    async def set_sulking_level(self, user_id: str, level: int, persona_id: str = None) -> bool:
        """
        Set the sulking level for a user and persona.
        
        Args:
            user_id: Unique user identifier
            level: Sulking level (0-3)
            persona_id: Optional tutor persona identifier
            
        Returns:
            True if successful
        """
        client = await self.get_client()
        key = f"chat:sulking:{user_id}:{persona_id}" if persona_id else f"chat:sulking:{user_id}"
        
        try:
            # Clamp level between 0 and 3
            level = max(0, min(3, level))
            await client.set(key, level)
            await client.expire(key, 7 * 24 * 60 * 60)  # 7 days
            return True
        except Exception as e:
            logger.error(f"Error setting sulking level: {e}")
            return False
    
    async def increment_sulking_level(self, user_id: str, persona_id: str = None) -> int:
        """
        Increment sulking level (max 3).
        
        Returns:
            New sulking level
        """
        current = await self.get_sulking_level(user_id, persona_id=persona_id)
        new_level = min(3, current + 1)
        await self.set_sulking_level(user_id, new_level, persona_id=persona_id)
        return new_level
    
    async def decrement_sulking_level(self, user_id: str, persona_id: str = None) -> int:
        """
        Decrement sulking level (min 0).
        
        Returns:
            New sulking level
        """
        current = await self.get_sulking_level(user_id, persona_id=persona_id)
        new_level = max(0, current - 1)
        await self.set_sulking_level(user_id, new_level, persona_id=persona_id)
        return new_level
    
    # ==================== User Profile ====================
    
    async def get_user_state(self, user_id: str) -> Dict[str, Any]:
        """
        Get complete user state including role and preferences.
        
        Returns:
            Dict with user_role, agent_role, sulking_level, etc.
        """
        client = await self.get_client()
        key = f"chat:state:{user_id}"
        
        try:
            state_json = await client.get(key)
            if state_json:
                return json.loads(state_json)
            else:
                # Default state
                return {
                    "user_role": "Sư huynh",
                    "agent_role": "Muội muội",
                    "sulking_level": 0,
                    "preferred_voice": "zh-CN-XiaoxiaoNeural"
                }
        except Exception as e:
            logger.error(f"Error getting user state: {e}")
            return {
                "user_role": "Sư huynh",
                "agent_role": "Muội muội",
                "sulking_level": 0,
                "preferred_voice": "zh-CN-XiaoxiaoNeural"
            }
    
    async def set_user_state(self, user_id: str, state: Dict[str, Any]) -> bool:
        """Save complete user state."""
        client = await self.get_client()
        key = f"chat:state:{user_id}"
        
        try:
            await client.set(key, json.dumps(state, ensure_ascii=False))
            await client.expire(key, 30 * 24 * 60 * 60)  # 30 days
            return True
        except Exception as e:
            logger.error(f"Error setting user state: {e}")
            return False
