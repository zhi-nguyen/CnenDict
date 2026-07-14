"""
AI Agent service using Google Gemini via Vertex AI.
Handles Chinese tutoring with structured output.
"""

import logging
import time
from typing import Any, Dict, List, Optional
from google import genai
from google.genai import types
from config import settings
from prompts import MAX_HISTORY_TURNS, get_system_instruction

logger = logging.getLogger(__name__)


class ChineseTutorAgent:
    """
    AI agent for Chinese language tutoring using Gemini via Vertex AI.
    Returns structured JSON responses with emotion, content, and actions.
    """
    
    # Define the response schema for structured output
    # Note: 'emotion' is first to enable fast parsing in stream mode
    RESPONSE_SCHEMA = types.Schema(
        type=types.Type.OBJECT,
        properties={
            "emotion": types.Schema(
                type=types.Type.STRING,
                enum=["neutral", "happy", "excited", "cheerful", "strict", "concerned", "sulking", "angry"],
                description="The emotion tag to control the avatar or TTS expression."
            ),
            "active_joy": types.Schema(
                type=types.Type.NUMBER,
                description="The calculated active joy value after stimulus absorption (0.0 to 1.0)."
            ),
            "active_sad": types.Schema(
                type=types.Type.NUMBER,
                description="The calculated active sad value after stimulus absorption (0.0 to 1.0)."
            ),
            "thought": types.Schema(
                type=types.Type.STRING,
                description="Internal reasoning about the user's intent and emotional calculation. Keep it short."
            ),
            "target_text": types.Schema(
                type=types.Type.STRING,
                description="The response in target language (Chinese, English, etc.). This will be converted to TTS audio."
            ),
            "translation_hint": types.Schema(
                type=types.Type.STRING,
                description="The translation or annotations in Vietnamese."
            ),
            "phonetic_guide": types.Schema(
                type=types.Type.STRING,
                description="Pinyin for Chinese or Oxford IPA UK for English."
            ),
            "action": types.Schema(
                type=types.Type.STRING,
                enum=["none", "correction", "quiz"],
                description="The action type."
            ),
            "quiz_list": types.Schema(
                type=types.Type.ARRAY,
                description="List of quiz items if action is 'quiz'.",
                items=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "id": types.Schema(type=types.Type.INTEGER),
                        "type": types.Schema(type=types.Type.STRING, enum=["fill_blank", "multiple_choice", "listening"]),
                        "question": types.Schema(type=types.Type.STRING),
                        "options": types.Schema(type=types.Type.ARRAY, items=types.Schema(type=types.Type.STRING)),
                        "answer": types.Schema(type=types.Type.STRING)
                     },
                     required=["id", "type", "question", "answer"]
                )
            )
        },
        required=["emotion", "active_joy", "active_sad", "thought", "target_text", "translation_hint", "phonetic_guide", "action", "quiz_list"]
    )
    
    def __init__(self):
        """Initialize the Gemini client using Vertex AI."""
        logger.info(f"Initializing Gemini Client with Vertex AI for model: {settings.GEMINI_MODEL_NAME}")
        
        # Configure HttpOptions for Vertex AI Priority PayGo routing
        http_options = types.HttpOptions(
            headers={
                "X-Vertex-AI-LLM-Request-Type": "shared",
                "X-Vertex-AI-LLM-Shared-Request-Type": "priority"
            }
        )
        
        self.client = genai.Client(
            vertexai=True, 
            location="global",
            http_options=http_options
        )
        self.model_name = settings.GEMINI_MODEL_NAME
    
    def _format_conversation_history(
        self, 
        conversation_history: List[Dict[str, Any]],
        learning_language: str = "zh"
    ) -> List[types.Content]:
        """
        Convert Redis conversation history to Gemini format.
        
        Args:
            conversation_history: List of dicts with 'role' and 'content' keys
            learning_language: The target language being learned ('zh' or 'en')
            
        Returns:
            List of Gemini Content objects
        """
        import json
        formatted_history = []
        
        for msg in conversation_history[-settings.MAX_HISTORY_TURNS:]:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            
            # Map roles to Gemini's expected format
            gemini_role = "user" if role == "user" else "model"
            
            # If assistant message, try to parse JSON and sanitize target_text
            if role == "assistant":
                try:
                    data = json.loads(content)
                    if isinstance(data, dict):
                        target_text = data.get("target_text", "")
                        content = self.sanitize_history_text(target_text, learning_language)
                except (json.JSONDecodeError, TypeError):
                    content = self.sanitize_history_text(content, learning_language)
            
            formatted_history.append(
                types.Content(
                    role=gemini_role,
                    parts=[types.Part(text=content)]
                )
            )
        
        return formatted_history
        
    @staticmethod
    def sanitize_history_text(text: str, learning_language: str) -> str:
        """
        Sanitize assistant conversation history to remove leaked Vietnamese words
        or recover Chinese sentences if the model outputted entirely in Vietnamese.
        """
        if not text:
            return ""
        if learning_language == "zh":
            import re
            # 1. Replace common wuxia pronouns that leak from Vietnamese
            replacements = {
                "Muội Muội": "妹妹",
                "Muội muội": "妹妹",
                "muội muội": "妹妹",
                "Sư Huynh": "师兄",
                "Sư huynh": "师兄",
                "sư huynh": "师兄",
                "Sư Tỷ": "师姐",
                "Sư tỷ": "师姐",
                "sư tỷ": "师姐",
                "Sư Đệ": "师弟",
                "Sư đệ": "师弟",
                "sư đệ": "师弟",
                "Tỷ Tỷ": "姐姐",
                "Tỷ tỷ": "姐姐",
                "tỷ tỷ": "姐姐",
                "Đồng Môn": "同门",
                "Đồng môn": "同门",
                "đồng môn": "同门",
            }
            for vi, zh in replacements.items():
                text = text.replace(vi, zh)
                
            # 2. Check if the text is entirely or mostly Vietnamese (Latin characters with diacritics).
            # We count characters to determine if it is mostly Vietnamese.
            latin_chars = len(re.findall(r'[a-zA-ZàáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđĐ]', text))
            chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
            
            total_len = chinese_chars + latin_chars
            if latin_chars > 0 and (chinese_chars == 0 or (latin_chars / total_len) > 0.4):
                # The model spoke Vietnamese. Let's translate common phrases or just fall back to a clean Chinese greeting/context
                phrases_map = {
                    "không bình luận": "不评论",
                    "dung mạo": "容貌",
                    "chỉ phụ trách": "只负责",
                    "việc dạy học": "教学",
                    "dạy học": "教学",
                    "quá lời rồi": "过奖了",
                    "xin chào": "你好",
                    "cảm ơn": "谢谢",
                }
                for vi, zh in phrases_map.items():
                    text = text.replace(vi, zh)
                for vi, zh in replacements.items():
                    text = text.replace(vi, zh)
                    
                # Remove any remaining Latin/Vietnamese words and extra spaces
                text = re.sub(r'[a-zA-ZàáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđĐ\s]+', '', text)
                
                # If empty, fallback to a safe sentence
                if not text:
                    text = "我们开始学习吧。"
        return text
    
    async def generate_response(
        self,
        user_text: str,
        user_role: str = "Sư huynh",
        agent_role: str = "Muội muội",
        sulking_level: int = 0,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        user_level: str = "Beginner",
        topic: str = "Daily Conversation",
        user_name: Optional[str] = None,
        learning_language: str = "zh"
    ) -> Dict[str, Any]:
        """
        Generate a structured response from the AI tutor.
        """
        try:
            # Get the dynamic system instruction based on the user's role and context
            system_instruction = get_system_instruction(
                user_role=user_role,
                agent_role=agent_role,
                sulking_level=sulking_level,
                user_level=user_level,
                topic=topic,
                user_name=user_name
            )
            
            # Prepare conversation history
            history = []
            if conversation_history:
                history = self._format_conversation_history(conversation_history, learning_language=learning_language)
            
            # Add current user message
            history.append(
                types.Content(
                    role="user",
                    parts=[types.Part(text=user_text)]
                )
            )
            
            # Configure generation parameters
            config = types.GenerateContentConfig(
                temperature=0.9,
                top_p=0.95,
                top_k=40,
                max_output_tokens=2048,
                response_mime_type="application/json",
                response_schema=self.RESPONSE_SCHEMA,
                system_instruction=system_instruction
            )
            
            logger.info(f"Calling Gemini API for user message: {user_text[:50]}...")
            
            # Start timing
            start_time = time.time()

            # Call Gemini API asynchronously
            response = await self.client.aio.models.generate_content(
                model=self.model_name,
                contents=history,
                config=config
            )
            
            # End timing
            end_time = time.time()
            duration_ms = (end_time - start_time) * 1000
            logger.info(f"[LATENCY] Gemini API Call: {duration_ms:.2f} ms")

            # Parse the JSON response
            import json_repair
            result = json_repair.loads(response.text)
            
            # Add usage metadata to result if available
            if response.usage_metadata:
                result["usage_metadata"] = {
                    "prompt_token_count": response.usage_metadata.prompt_token_count,
                    "candidates_token_count": response.usage_metadata.candidates_token_count,
                    "total_token_count": response.usage_metadata.total_token_count
                }
            
            logger.info(f"Gemini response received: emotion={result.get('emotion')}, action={result.get('action')}")
            
            return result
            
        except Exception as e:
            logger.error(f"Error generating AI response: {e}", exc_info=True)
            return self._get_fallback_response(user_text, sulking_level)
    
    def _get_fallback_response(
        self, 
        user_text: str, 
        sulking_level: int
    ) -> Dict[str, Any]:
        """
        Generate a fallback response when API fails.
        """
        if sulking_level >= 2:
            return {
                "thought": "API error, using fallback",
                "target_text": "哼，现在系统出问题了，师妹暂时不能教你了。",
                "translation_hint": "Hừm, hệ thống đang có vấn đề, tiểu sư muội tạm thời không thể dạy anh được.",
                "phonetic_guide": "Hng, xiànzài xìtǒng chū wèntí le, shī mèi zànshí bù néng jiāo nǐ le.",
                "emotion": "sulking",
                "action": "none",
                "quiz_list": []
            }
        else:
            return {
                "thought": "API error, using fallback",
                "target_text": "师兄，系统有点小问题，稍等一下好吗？",
                "translation_hint": "Sư huynh, hệ thống có chút vấn đề, chờ một chút được không?",
                "phonetic_guide": "Shī xiōng, xìtǒng yǒudiǎn xiǎo wèntí, shāo děng yīxià hǎo ma?",
                "emotion": "concerned",
                "action": "none",
                "quiz_list": []
            }
    
    async def test_connection(self) -> bool:
        """
        Test if the Gemini API connection is working.
        """
        try:
            response = await self.client.aio.models.generate_content(
                model=self.model_name,
                contents="你好",
                config=types.GenerateContentConfig(
                    max_output_tokens=10
                )
            )
            return bool(response.text)
        except Exception as e:
            import sys
            import traceback
            print(f"ERROR: API connection test failed: {e}", file=sys.stderr, flush=True)
            traceback.print_exc(file=sys.stderr)
            logger.error(f"API connection test failed: {e}")
            return False
