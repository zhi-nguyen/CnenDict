import logging
import json

from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from core_project.ws_utils import get_redis_client
from .tasks import dispatch_chat_request
from .persona_generator import generate_random_persona
from .models import ChatPersona, ChatMessage, ChatSummary

logger = logging.getLogger(__name__)


class XiaoyueChatPersonasListView(APIView):
    """
    List all AI Tutor Personas created by the user.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            personas = ChatPersona.objects.filter(user=request.user).order_by("-updated_at")
            result = []
            for p in personas:
                # Retrieve current emotion state from Redis if available, fallback to DB values
                redis_client = get_redis_client()
                emotion_key = f"chat:emotion:{request.user.id}:{p.id}"
                emotion_data = redis_client.get(emotion_key)
                if emotion_data:
                    emotion = json.loads(emotion_data.decode("utf-8") if isinstance(emotion_data, bytes) else emotion_data)
                    joy_current = emotion.get("joy", 0.5)
                    sad_current = emotion.get("sad", 0.1)
                else:
                    joy_current = p.joy_current
                    sad_current = p.sad_current

                result.append({
                    "id": str(p.id),
                    "agent_name": p.agent_name,
                    "agent_birth_year": p.agent_birth_year,
                    "age_diff": p.age_diff,
                    "personality_type": p.personality_type,
                    "personality_desc": p.personality_desc,
                    "avatar_emoji": p.avatar_emoji,
                    "avatar_url": p.avatar_url,
                    "context_setting": p.context_setting,
                    "learning_language": p.learning_language,
                    "user_level": p.user_level,
                    "user_honorific": p.user_honorific,
                    "agent_self_ref": p.agent_self_ref,
                    "relation_choice": p.relation_type,
                    "joy_current": joy_current,
                    "sad_current": sad_current,
                    "created_at": p.created_at.isoformat(),
                    "updated_at": p.updated_at.isoformat(),
                })
            return Response(result, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Failed to list personas for user {request.user.id}: {e}", exc_info=True)
            return Response(
                {"detail": "Không thể lấy danh sách gia sư."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class XiaoyueChatSendView(APIView):
    """
    Dispatch a chat request to the AI Chat Service via Celery + Redis Pub/Sub.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        user_text = request.data.get("user_text", "").strip()
        persona_id = request.data.get("persona_id")

        if not user_text:
            return Response(
                {"detail": "Nội dung tin nhắn không được để trống."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not persona_id:
            return Response(
                {"detail": "Thiếu thông tin định danh Gia sư (persona_id)."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Get user tier for queue routing
        user_tier = (
            getattr(user.subscription, "tier", "Free")
            if hasattr(user, "subscription")
            else "Free"
        )

        try:
            persona_obj = ChatPersona.objects.get(user=user, id=persona_id)
        except ChatPersona.DoesNotExist:
            return Response(
                {"detail": "Không tìm thấy Gia sư yêu cầu."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Build persona dict payload
        persona = {
            "id": str(persona_obj.id),
            "agent_name": persona_obj.agent_name,
            "agent_birth_year": persona_obj.agent_birth_year,
            "age_diff": persona_obj.age_diff,
            "personality_type": persona_obj.personality_type,
            "personality_desc": persona_obj.personality_desc,
            "avatar_emoji": persona_obj.avatar_emoji,
            "context_setting": persona_obj.context_setting,
            "learning_language": persona_obj.learning_language,
            "user_level": persona_obj.user_level,
            "user_honorific": persona_obj.user_honorific,
            "agent_self_ref": persona_obj.agent_self_ref,
            "relation_choice": persona_obj.relation_type,
            "joy_sensitivity": persona_obj.joy_sensitivity,
            "joy_decay_rate": persona_obj.joy_decay_rate,
            "sad_sensitivity": persona_obj.sad_sensitivity,
            "sad_decay_rate": persona_obj.sad_decay_rate,
        }

        # Retrieve current emotion state from Redis (or DB fallback)
        try:
            redis_client = get_redis_client()
            emotion_key = f"chat:emotion:{user.id}:{persona_obj.id}"
            emotion_data = redis_client.get(emotion_key)
            if emotion_data:
                emotion = json.loads(emotion_data.decode("utf-8") if isinstance(emotion_data, bytes) else emotion_data)
            else:
                emotion = {"joy": persona_obj.joy_current, "sad": persona_obj.sad_current}
        except Exception as e:
            logger.error(f"Failed to fetch emotion from Redis for persona {persona_obj.id}: {e}")
            emotion = {"joy": persona_obj.joy_current, "sad": persona_obj.sad_current}

        # Dispatch to Celery task with tier routing, passing persona_id
        dispatch_chat_request.apply_async(
            args=[
                str(user.id),
                user_text,
            ],
            kwargs={
                "user_tier": user_tier,
                "persona": persona,
                "emotion": emotion,
                "persona_id": str(persona_obj.id),
            },
        )

        return Response(
            {
                "status": "success",
                "message": "Chat request dispatched successfully.",
            },
            status=status.HTTP_202_ACCEPTED,
        )


class XiaoyueChatSulkingView(APIView):
    """
    Get the current sulking level of the authenticated user's active tutor.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user_id = str(request.user.id)
        persona_id = request.query_params.get("persona_id")
        if not persona_id:
            return Response(
                {"detail": "Thiếu persona_id."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            redis_client = get_redis_client()
            key = f"chat:sulking:{user_id}:{persona_id}"
            level = redis_client.get(key)
            sulking_level = int(level) if level else 0
        except Exception as e:
            logger.error(f"Failed to fetch sulking level for persona {persona_id}: {e}")
            sulking_level = 0

        return Response({
            "user_id": user_id,
            "persona_id": persona_id,
            "sulking_level": sulking_level,
        })


class XiaoyueChatClearView(APIView):
    """
    Clear conversation history, reset state counter, reset sulking level, emotions and past context summaries for a specific tutor.
    Does NOT delete the tutor persona record itself, just its chat history.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user_id = str(request.user.id)
        persona_id = request.data.get("persona_id")

        if not persona_id:
            return Response(
                {"detail": "Thiếu thông tin định danh Gia sư (persona_id)."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            redis_client = get_redis_client()
            redis_client.delete(f"chat:history:{user_id}:{persona_id}")
            redis_client.delete(f"chat:sulking:{user_id}:{persona_id}")
            redis_client.delete(f"chat:counter:{user_id}:{persona_id}")
            redis_client.delete(f"chat:emotion:{user_id}:{persona_id}")
            
            # Delete past RAG summaries and chat messages from database for this persona
            ChatSummary.objects.filter(user_id=request.user.id, persona_id=persona_id).delete()
            ChatMessage.objects.filter(user_id=request.user.id, persona_id=persona_id).delete()
            
            logger.info(f"Cleared chat history, counter, emotion, summaries, and messages for persona {persona_id} (user {user_id})")
        except Exception as e:
            logger.error(f"Failed to clear chat data for persona {persona_id}: {e}")
            return Response(
                {"detail": "Không thể xóa lịch sử trò chuyện."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response({
            "status": "success",
            "user_id": user_id,
            "persona_id": persona_id,
        })


class XiaoyueChatPersonaView(APIView):
    """
    Get, Delete or dynamically generate/create a random AI persona.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        persona_id = request.query_params.get("persona_id")
        
        try:
            if persona_id:
                persona_obj = ChatPersona.objects.get(user=user, id=persona_id)
            else:
                persona_obj = ChatPersona.objects.filter(user=user).first()
                
            if not persona_obj:
                return Response(
                    {"detail": "Vui lòng thiết lập thông tin gia sư."},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            # Retrieve emotional state from Redis or DB fallback
            redis_client = get_redis_client()
            emotion_key = f"chat:emotion:{user.id}:{persona_obj.id}"
            emotion_data = redis_client.get(emotion_key)
            if emotion_data:
                emotion = json.loads(emotion_data.decode("utf-8") if isinstance(emotion_data, bytes) else emotion_data)
                joy_current = emotion.get("joy", 0.5)
                sad_current = emotion.get("sad", 0.1)
            else:
                joy_current = persona_obj.joy_current
                sad_current = persona_obj.sad_current
                
            result = {
                "id": str(persona_obj.id),
                "agent_name": persona_obj.agent_name,
                "agent_birth_year": persona_obj.agent_birth_year,
                "age_diff": persona_obj.age_diff,
                "personality_type": persona_obj.personality_type,
                "personality_desc": persona_obj.personality_desc,
                "avatar_emoji": persona_obj.avatar_emoji,
                "avatar_url": persona_obj.avatar_url,
                "context_setting": persona_obj.context_setting,
                "learning_language": persona_obj.learning_language,
                "user_level": persona_obj.user_level,
                "user_honorific": persona_obj.user_honorific,
                "agent_self_ref": persona_obj.agent_self_ref,
                "relation_choice": persona_obj.relation_type,
                "joy_current": joy_current,
                "sad_current": sad_current,
            }
            return Response(result, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Failed to retrieve persona for user {user.id}: {e}", exc_info=True)
            return Response(
                {"detail": "Lỗi xử lý thông tin gia sư."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def post(self, request):
        user = request.user
        user_name = request.data.get("user_name")
        gender = request.data.get("gender")
        birth_year = request.data.get("birth_year")
        context_setting = request.data.get("context_setting")
        learning_language = request.data.get("learning_language", "zh")
        user_level = request.data.get("user_level", "Beginner")
        relation_choice = request.data.get("relation_choice")
        
        if not all([user_name, gender, birth_year, context_setting]):
            return Response(
                {"detail": "Thiếu thông tin bắt buộc: user_name, gender, birth_year, context_setting."},
                status=status.HTTP_400_BAD_REQUEST
            )
            
        try:
            persona_dict = generate_random_persona(
                str(user_name).strip(),
                str(gender).strip(),
                int(birth_year),
                str(context_setting).strip(),
                str(learning_language).strip(),
                str(user_level).strip(),
                relation_choice=relation_choice
            )
            
            persona_obj = ChatPersona.objects.create(
                user=user,
                agent_name=persona_dict["agent_name"],
                agent_birth_year=persona_dict["agent_birth_year"],
                age_diff=persona_dict["age_diff"],
                personality_type=persona_dict["personality_type"],
                personality_desc=persona_dict["personality_desc"],
                avatar_emoji=persona_dict["avatar_emoji"],
                context_setting=persona_dict["context_setting"],
                learning_language=persona_dict["learning_language"],
                user_level=persona_dict["user_level"],
                user_honorific=persona_dict["user_honorific"],
                agent_self_ref=persona_dict["agent_self_ref"],
                relation_type=persona_dict.get("relation_type", "default"),
            )
            
            # Reset emotional state in Redis
            redis_client = get_redis_client()
            redis_client.set(f"chat:emotion:{user.id}:{persona_obj.id}", json.dumps({"joy": 0.5, "sad": 0.1}))

            # Trigger avatar generation asynchronously
            from .tasks import generate_persona_avatar_task
            generate_persona_avatar_task.delay(str(persona_obj.id))
            
            result = {
                "id": str(persona_obj.id),
                "agent_name": persona_obj.agent_name,
                "agent_birth_year": persona_obj.agent_birth_year,
                "age_diff": persona_obj.age_diff,
                "personality_type": persona_obj.personality_type,
                "personality_desc": persona_obj.personality_desc,
                "avatar_emoji": persona_obj.avatar_emoji,
                "avatar_url": persona_obj.avatar_url,
                "context_setting": persona_obj.context_setting,
                "learning_language": persona_obj.learning_language,
                "user_level": persona_obj.user_level,
                "user_honorific": persona_obj.user_honorific,
                "agent_self_ref": persona_obj.agent_self_ref,
                "relation_choice": persona_obj.relation_type,
                "joy_current": 0.5,
                "sad_current": 0.1,
            }
            return Response(result, status=status.HTTP_201_CREATED)
        except ValueError:
            return Response(
                {"detail": "Năm sinh phải là số nguyên hợp lệ."},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error(f"Failed to generate and save persona for user {user.id}: {e}", exc_info=True)
            return Response(
                {"detail": "Lỗi khi tạo ngẫu nhiên thông tin gia sư."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def delete(self, request):
        """
        Delete a specific tutor persona and all associated messages.
        """
        user = request.user
        persona_id = request.data.get("persona_id") or request.query_params.get("persona_id")
        if not persona_id:
            return Response(
                {"detail": "Thiếu persona_id."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            persona_obj = ChatPersona.objects.get(user=user, id=persona_id)
            persona_obj.delete()

            redis_client = get_redis_client()
            redis_client.delete(f"chat:history:{user.id}:{persona_id}")
            redis_client.delete(f"chat:sulking:{user.id}:{persona_id}")
            redis_client.delete(f"chat:counter:{user.id}:{persona_id}")
            redis_client.delete(f"chat:emotion:{user.id}:{persona_id}")

            return Response({
                "status": "success",
                "message": f"Deleted persona {persona_id} and all related messages successfully."
            }, status=status.HTTP_200_OK)
        except ChatPersona.DoesNotExist:
            return Response(
                {"detail": "Không tìm thấy Gia sư yêu cầu."},
                status=status.HTTP_404_NOT_FOUND,
            )
        except Exception as e:
            logger.error(f"Failed to delete persona {persona_id}: {e}", exc_info=True)
            return Response(
                {"detail": "Lỗi khi xóa gia sư."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class XiaoyueChatHistoryView(APIView):
    """
    Get paginated chat history for a specific tutor:
    - First load (db_offset not provided): Loads up to 20 messages from Redis. Falls back to DB if empty.
    - Subsequent loads (db_offset provided): Loads older messages from PostgreSQL db using offset.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        user_id = str(user.id)
        persona_id = request.query_params.get("persona_id")
        db_offset_str = request.query_params.get("db_offset")
        limit = int(request.query_params.get("limit", 20))
        
        if not persona_id:
            # Fallback to the user's most recent persona if persona_id not specified
            persona_obj = ChatPersona.objects.filter(user=user).first()
            if not persona_obj:
                return Response({
                    "history": [],
                    "has_more": False,
                    "db_offset": 0
                }, status=status.HTTP_200_OK)
            persona_id = str(persona_obj.id)

        try:
            redis_client = get_redis_client()
            
            # --- CASE 1: First load (Retrieve from Redis) ---
            if db_offset_str is None:
                redis_key = f"chat:history:{user_id}:{persona_id}"
                redis_data = redis_client.lrange(redis_key, -20, -1)
                
                messages = []
                for item in redis_data:
                    if isinstance(item, bytes):
                        item = item.decode("utf-8")
                    try:
                        msg_dict = json.loads(item)
                        role = msg_dict.get("role", "user")
                        content = msg_dict.get("content", "")
                        
                        if role == "assistant":
                            try:
                                content_data = json.loads(content)
                                if isinstance(content_data, dict):
                                    messages.append({
                                        "id": f"redis_{len(messages)}",
                                        "sender": "agent",
                                        "text": content_data.get("target_text", ""),
                                        "translation": content_data.get("translation_hint", ""),
                                        "pinyin": content_data.get("phonetic_guide", ""),
                                        "emotion": content_data.get("emotion", "neutral"),
                                        "thought": content_data.get("thought", ""),
                                        "correction": content_data.get("correction_detail"),
                                        "quizzes": content_data.get("quiz_list"),
                                        "isStreaming": False
                                    })
                                    continue
                            except (json.JSONDecodeError, TypeError):
                                pass
                                
                        messages.append({
                            "id": f"redis_{len(messages)}",
                            "sender": "user" if role == "user" else "agent",
                            "text": content,
                            "isStreaming": False
                        })
                    except Exception:
                        continue
                
                # If Redis has active messages, check if DB has older messages
                if messages:
                    has_more = ChatMessage.objects.filter(user=user, persona_id=persona_id).exists()
                    return Response({
                        "history": messages,
                        "has_more": has_more,
                        "db_offset": 0
                    }, status=status.HTTP_200_OK)
                
                # If Redis is completely empty (e.g. expired session), fall back to DB first page
                db_offset = 0
            else:
                db_offset = int(db_offset_str)
                
            # --- CASE 2: Paginate older messages from DB ---
            db_msgs = ChatMessage.objects.filter(user=user, persona_id=persona_id).order_by("-timestamp")[db_offset:db_offset + limit]
            
            messages = []
            for msg in reversed(db_msgs):
                messages.append({
                    "id": f"db_{msg.id}",
                    "sender": "user" if msg.role == "user" else "agent",
                    "text": msg.content,
                    "timestamp": msg.timestamp.isoformat(),
                    "isStreaming": False
                })
                
            total_db_count = ChatMessage.objects.filter(user=user, persona_id=persona_id).count()
            has_more = total_db_count > (db_offset + len(db_msgs))
            
            return Response({
                "history": messages,
                "has_more": has_more,
                "db_offset": db_offset + len(db_msgs)
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Failed to fetch paginated chat history for persona {persona_id}: {e}", exc_info=True)
            return Response(
                {"detail": "Không thể lấy lịch sử cuộc trò chuyện."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

