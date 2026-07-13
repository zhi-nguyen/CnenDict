import json
import logging
from celery import shared_task
from core_project.ws_utils import get_redis_client

logger = logging.getLogger(__name__)


@shared_task
def persist_chat_messages(user_id: str, messages: list, persona_id: str = None) -> bool:
    """
    Celery task to persist chat messages to the database.
    messages: list of dicts [{"role": "...", "content": "..."}]
    """
    from django.contrib.auth import get_user_model
    from .models import ChatMessage

    User = get_user_model()
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        logger.error(f"User with id {user_id} does not exist. Cannot persist chat messages.")
        return False

    chat_messages = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        
        # If it's a JSON string from the assistant, parse and extract only target_text to persist in DB
        if role == "assistant":
            try:
                data = json.loads(content)
                if isinstance(data, dict):
                    content = data.get("target_text", content)
            except (json.JSONDecodeError, TypeError):
                pass
                
        chat_messages.append(
            ChatMessage(
                user=user,
                persona_id=persona_id,
                role=role,
                content=content,
            )
        )

    if chat_messages:
        try:
            ChatMessage.objects.bulk_create(chat_messages)
            logger.info(f"Persisted {len(chat_messages)} messages to DB for user {user_id} (persona {persona_id})")
            return True
        except Exception as e:
            logger.error(f"Failed to bulk create ChatMessage: {e}")
            return False
    return False


@shared_task(queue='queue_chat')
def dispatch_chat_request(user_id, user_text, user_role=None, user_level=None, topic=None, user_name=None, **kwargs):
    """
    Celery task to dispatch a chat request to Redis Pub/Sub.
    1. Increments chat:counter:{user_id}:{persona_id}
    2. Trims active chat history in Redis to 20 messages (persisting overflow to DB)
    3. If counter > 10, queries pgvector to get past context related to the user's input for this specific persona
    4. If counter % 6 == 0, dispatches async_summarize_and_embed for the last 6 messages
    5. Publishes complete payload (with user_text, persona_id, and past_context) to Redis channel
    """
    coin_group_id = kwargs.pop("coin_group_id", None)
    coin_lang = kwargs.pop("coin_lang", None)
    coin_cost = kwargs.pop("coin_cost", 0)

    try:
        redis_client = get_redis_client()
        from django.conf import settings as django_settings

        user_id_str = str(user_id)
        persona_id = kwargs.get("persona_id")

        if not persona_id:
            logger.warning(f"dispatch_chat_request called without persona_id for user {user_id_str}")

        # 1. State Counter (scoped by persona)
        counter_key = f"chat:counter:{user_id_str}:{persona_id}" if persona_id else f"chat:counter:{user_id_str}"
        counter = redis_client.incr(counter_key)
        redis_client.expire(counter_key, 30 * 24 * 60 * 60)  # 30 days

        # 2. Check and persist chat history exceeding 20 messages (10 turns) (scoped by persona)
        redis_key = f"chat:history:{user_id_str}:{persona_id}" if persona_id else f"chat:history:{user_id_str}"
        try:
            current_len = redis_client.llen(redis_key)
            if current_len > 20:
                overflow_count = current_len - 20
                popped_messages = []
                for _ in range(overflow_count):
                    val = redis_client.lpop(redis_key)
                    if val:
                        if isinstance(val, bytes):
                            val = val.decode("utf-8")
                        popped_messages.append(json.loads(val))

                if popped_messages:
                    persist_chat_messages.delay(user_id_str, popped_messages, persona_id=persona_id)
        except Exception as trim_err:
            logger.error(f"Failed to check/trim chat history in Redis for user {user_id_str} (persona {persona_id}): {trim_err}")

        # 3. Retrieve past context via RAG if counter > threshold
        past_context = ""
        if counter > django_settings.CHAT_RAG_THRESHOLD:
            try:
                past_context = _retrieve_rag_context(user_id_str, user_text, persona_id=persona_id)
            except Exception as rag_err:
                logger.error(f"Failed to retrieve RAG context for user {user_id_str} (persona {persona_id}): {rag_err}", exc_info=True)

        # 4. Trigger periodic summarization if counter is a multiple of cycle
        if counter % django_settings.CHAT_SUMMARY_CYCLE == 0:
            try:
                # 6 turns = 12 messages (1 user message + 1 assistant message per turn)
                num_messages = django_settings.CHAT_SUMMARY_CYCLE * 2
                recent_vals = redis_client.lrange(redis_key, -num_messages, -1)
                messages = []
                for val in recent_vals:
                    if val:
                        if isinstance(val, bytes):
                            val = val.decode("utf-8")
                        messages.append(json.loads(val))
                if messages:
                    async_summarize_and_embed.delay(user_id_str, messages, persona_id=persona_id)
            except Exception as sum_err:
                logger.error(f"Failed to trigger summarization for user {user_id_str} (persona {persona_id}): {sum_err}")

        # 5. Extract persona and emotion (with fallbacks for legacy/direct calls)
        persona = kwargs.get("persona")
        emotion = kwargs.get("emotion", {"joy": 0.5, "sad": 0.1})

        if not persona:
            # Generate a default wuxia persona to avoid crash
            persona = {
                "id": persona_id,
                "agent_name": "小月",
                "agent_birth_year": 2005,
                "personality_type": "cheerful",
                "personality_desc": "Vui vẻ, hoạt bát",
                "avatar_emoji": "🌸",
                "context_setting": kwargs.get("context_setting") or "wuxia",
                "learning_language": kwargs.get("learning_language") or "zh",
                "user_level": user_level or "Beginner",
                "user_name": user_name or "Sư huynh",
                "user_gender": "male",
                "user_birth_year": 2004,
                "user_honorific": user_role or "师兄",
                "agent_self_ref": "妹妹",
                "joy_sensitivity": 1.5,
                "joy_decay_rate": 0.2,
                "sad_sensitivity": 0.4,
                "sad_decay_rate": 0.8
            }

        # 6. Publish the chat request with past context to Redis for FastAPI service
        channel = f"ai:chat:request:{user_id_str}"
        payload = {
            "user_id": user_id_str,
            "persona_id": persona_id,
            "user_text": user_text,
            
            # Persona fields
            "agent_name": persona.get("agent_name"),
            "agent_birth_year": persona.get("agent_birth_year"),
            "personality_type": persona.get("personality_type"),
            "personality_desc": persona.get("personality_desc"),
            "avatar_emoji": persona.get("avatar_emoji"),
            "context_setting": persona.get("context_setting"),
            "learning_language": persona.get("learning_language"),
            "user_level": persona.get("user_level"),
            "user_name": persona.get("user_name"),
            "user_gender": persona.get("user_gender"),
            "user_birth_year": persona.get("user_birth_year"),
            "user_honorific": persona.get("user_honorific"),
            "agent_self_ref": persona.get("agent_self_ref"),
            
            # Multipliers
            "joy_sensitivity": persona.get("joy_sensitivity"),
            "joy_decay_rate": persona.get("joy_decay_rate"),
            "sad_sensitivity": persona.get("sad_sensitivity"),
            "sad_decay_rate": persona.get("sad_decay_rate"),
            
            # Current emotion state
            "joy_current": emotion.get("joy", 0.5),
            "sad_current": emotion.get("sad", 0.1),
            
            "past_context": past_context,
        }
        
        redis_client.publish(channel, json.dumps(payload, ensure_ascii=False))
        logger.info(f"Dispatched chat request for user {user_id_str} (persona {persona_id}) with RAG: bool({bool(past_context)}), lang: {payload['learning_language']}, context: {payload['context_setting']}, AI: {payload['agent_name']} ({payload['personality_type']})")
        return True
    except Exception as e:
        logger.error(f"Failed to dispatch chat request: {e}", exc_info=True)
        # Fallback refund
        if coin_group_id and coin_lang and coin_cost > 0:
            try:
                from apps.gamification.coin_service import CoinService
                from django.contrib.auth import get_user_model
                User = get_user_model()
                user = User.objects.get(id=user_id)
                CoinService.refund_coins(
                    user, coin_lang, coin_cost,
                    reference_id=coin_group_id,
                    note='Refund: dispatch_chat_request failed'
                )
                logger.info(f"Refunded {coin_cost} coins for failed chat dispatch (group={coin_group_id})")
            except Exception as refund_err:
                logger.error(f"CRITICAL: Failed to refund coins after chat dispatch error: {refund_err}", exc_info=True)
        return False



@shared_task(bind=True, max_retries=2, default_retry_delay=30, queue='queue_chat')
def async_summarize_and_embed(self, user_id: str, messages: list, persona_id: str = None) -> bool:
    """
    Asynchronous Celery pipeline to:
    1. Summarize conversation via Gemini model
    2. Vectorize the summary using text-embedding-004
    3. Save the result to ChatSummary table in PostgreSQL linked to the persona
    """
    from django.conf import settings as django_settings
    from django.contrib.auth import get_user_model
    from .models import ChatSummary, ChatPersona
    from google import genai

    logger.info(f"Starting async_summarize_and_embed for user {user_id} (persona {persona_id}) with {len(messages)} messages")
    
    User = get_user_model()
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        logger.error(f"User {user_id} does not exist. Cannot save summary.")
        return False

    try:
        # Check that persona exists
        if persona_id:
            try:
                persona_obj = ChatPersona.objects.get(id=persona_id, user=user)
            except ChatPersona.DoesNotExist:
                logger.error(f"ChatPersona {persona_id} does not exist. Cannot save summary.")
                return False
        else:
            persona_obj = None

        # Initialize Gemini Client via Vertex AI
        client = genai.Client(vertexai=True, location="global")

        # 1. Summarization prompt
        conv_lines = []
        for m in messages:
            role = m.get('role', 'user')
            content = m.get('content', '')
            if role == 'assistant':
                try:
                    data = json.loads(content)
                    if isinstance(data, dict):
                        target_text = data.get("target_text", "")
                        translation = data.get("translation_hint", "")
                        content = f"{target_text} ({translation})" if translation else target_text
                except (json.JSONDecodeError, TypeError):
                    pass
            conv_lines.append(f"{role}: {content}")
            
        conv_text = "\n".join(conv_lines)
        prompt = (
            "Hãy tóm tắt đoạn hội thoại sau dưới 3 câu, tuân thủ các yêu cầu sau:\n"
            "1. Đặc biệt ghi lại chính xác bất kỳ kế hoạch, cuộc hẹn, lời hứa hoặc ý định tương lai nào được nhắc đến (ví dụ: hứa ngày mai đi ăn, đi chơi, luyện kiếm).\n"
            "2. Ghi lại các thông tin cá nhân quan trọng, sở thích, yêu cầu hoặc quy tắc cụ thể mà người dùng đưa ra (ví dụ: yêu cầu cấm trả lời trong 10 câu).\n"
            "3. Viết một cách trực tiếp, rõ ràng và thực tế các chi tiết cụ thể (ví dụ: viết rõ 'Sư huynh hứa dẫn Sư muội đi ăn' thay vì dùng ẩn ý hoặc bóng gió).\n"
            "4. Tóm tắt diễn biến chính của cuộc trò chuyện một cách ngắn gọn.\n\n"
            "Đoạn hội thoại:\n"
            f"{conv_text}"
        )

        response = client.models.generate_content(
            model=django_settings.GEMINI_MODEL_NAME,
            contents=prompt,
        )
        summary_text = response.text.strip()
        if not summary_text:
            logger.warning("Gemini returned empty summary text.")
            return False

        # 2. Embedding creation
        logger.info(f"Generating embedding for summary of user {user_id} (persona {persona_id})")
        embed_resp = client.models.embed_content(
            model=django_settings.GEMINI_EMBEDDING_MODEL,
            contents=summary_text,
        )
        embedding_values = embed_resp.embeddings[0].values  # List[float] (768 dimensions)

        # 3. Store to PostgreSQL
        ChatSummary.objects.create(
            user=user,
            persona=persona_obj,
            summary_text=summary_text,
            embedding=embedding_values,
            message_count=len(messages),
        )
        logger.info(f"Successfully saved ChatSummary for user {user_id} (persona {persona_id})")
        return True

    except Exception as e:
        logger.error(f"Error in async_summarize_and_embed for user {user_id} (persona {persona_id}): {e}", exc_info=True)
        try:
            self.retry(exc=e)
        except Exception:
            pass
        return False


def _retrieve_rag_context(user_id: str, query_text: str, persona_id: str = None) -> str:
    """
    Synchronous helper to retrieve relevant past summaries using cosine similarity.
    """
    from django.conf import settings as django_settings
    from .models import ChatSummary
    from pgvector.django import CosineDistance
    from google import genai

    if not query_text.strip():
        return ""

    logger.info(f"Retrieving RAG context for user {user_id} (persona {persona_id})")
    
    # 1. Create embedding for the query
    client = genai.Client(vertexai=True, location="global")
    embed_resp = client.models.embed_content(
        model=django_settings.GEMINI_EMBEDDING_MODEL,
        contents=query_text,
    )
    query_vector = embed_resp.embeddings[0].values

    # 2. Query with cosine distance (pgvector)
    summaries = (
        ChatSummary.objects
        .filter(user_id=user_id, persona_id=persona_id)
        .annotate(distance=CosineDistance("embedding", query_vector))
        .order_by("distance")
        [:django_settings.CHAT_RAG_TOP_K]
    )

    valid_summaries = [s for s in summaries if s.distance is not None and s.distance < 0.6] # similarity threshold of ~0.4+ (distance < 0.6)
    if not valid_summaries:
        logger.info(f"No relevant past context found for user {user_id} (persona {persona_id}) (top distance: {summaries[0].distance if summaries else 'N/A'})")
        return ""

    # 3. Format context
    context_lines = [f"- {s.summary_text}" for s in valid_summaries]
    logger.info(f"Found {len(context_lines)} relevant past summaries for user {user_id} (persona {persona_id})")
    return (
        "Đây là ngữ cảnh từ các cuộc trò chuyện trước đó với người dùng:\n"
        + "\n".join(context_lines)
    )


@shared_task(queue='queue_chat')
def generate_persona_avatar_task(persona_id: str) -> str:
    """
    Celery task to generate avatar for an AI Tutor using the standalone image_service.
    """
    import requests
    from .models import ChatPersona
    from core_project.ws_utils import ws_notify

    try:
        persona_obj = ChatPersona.objects.get(id=persona_id)
    except ChatPersona.DoesNotExist:
        logger.error(f"ChatPersona with id {persona_id} does not exist.")
        return ""

    # Determine tutor (agent) gender (default to female since most presets are female)
    female_indicators = ["妹妹", "姐姐", "Chị", "Cô", "Sư tỷ", "Tỷ tỷ", "Helen", "female", "Sư Phụ", "Sư phụ", "为师", "仙子", "仙姑"]
    is_female = any(ind in (persona_obj.agent_self_ref or "") or ind in (persona_obj.agent_name or "") for ind in female_indicators)
    gender_vietnamese = "nữ" if (is_female or not persona_obj.agent_self_ref) else "nam"

    info_dict = {
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
        "joy_current": persona_obj.joy_current,
        "sad_current": persona_obj.sad_current,
    }
    json_info = json.dumps({k: v for k, v in info_dict.items() if v is not None}, ensure_ascii=False, indent=2)

    gender_english = "female" if (is_female or not persona_obj.agent_self_ref) else "male"

    # Determine prompt flavor based on relationship hierarchy (professor, interviewer, master)
    is_wuxia_master = persona_obj.relation_type == "master"
    is_mature = persona_obj.relation_type in ["professor", "interviewer"]
    
    if is_wuxia_master:
        # Wuxia master: focused prompt for celestial fairy / immortal master
        personality_hint = "cold and aloof, sharp and majestic gaze" if persona_obj.personality_type == "cold" else "gentle and serene, kind and compassionate gaze"
        prompt = (
            f"Masterpiece, best quality, 3D digital art, Chinese 3D donghua style, CG animation render. "
            f"A beautiful young Chinese {gender_english} immortal master (Xianxia goddess, fairy), {personality_hint}. "
            f"Wearing flowing white and light blue ancient Chinese hanfu robes, elegant celestial dress. "
            f"Long white/silver hair tied up with an exquisite jade hair pin (strictly no black hair). "
            f"Hands are elegantly hidden inside her wide sleeves (hands hidden in wide sleeves). "
            f"Standing gracefully on a mountain peak surrounded by ethereal sea of clouds and swirling wind. "
            f"Mystical Xianxia aesthetic, soft glowing ambient lighting, Octane Render, Unreal Engine 5, cinematic lighting, sharp focus, highly detailed skin and clothing textures."
        )
    elif is_mature:
        personality_hint = "professional and intellectual" if persona_obj.personality_type == "strict" else "gentle and friendly"
        prompt = (
            f"Masterpiece, best quality, highly detailed anime digital art, upper body portrait. "
            f"A beautiful and smart young {gender_english} tutor, {personality_hint} expression. "
            f"Mature look but cute, friendly eyes looking at the viewer. "
            f"Modern classroom or home study office background, soft warm lighting, neat and elegant appearance, sharp focus."
        )
    else:
        # Peer/classmate/colleague roles
        personality_hint = "happy and cheerful" if persona_obj.personality_type == "cheerful" else "gentle and smiling"
        prompt = (
            f"Masterpiece, best quality, highly detailed anime digital art, upper body avatar portrait. "
            f"A beautiful and cute young {gender_english} classmate, {personality_hint} expression. "
            f"Bright friendly smile, looking towards the viewer. "
            f"Modern casual clothing, clean study cafe or campus background, soft natural lighting, vibrant colors."
        )

    # Standalone image-service URL inside the docker network
    IMAGE_SERVICE_URL = "http://image-service:8003/api/v1/image/generate"

    try:
        logger.info(f"Sending avatar request for persona {persona_id} with prompt: {prompt}")
        res = requests.post(
            IMAGE_SERVICE_URL,
            json={
                "word_id": f"persona_{persona_id}",
                "lang": persona_obj.learning_language,
                "prompt": prompt
            },
            timeout=30
        )
        if res.status_code == 200:
            data = res.json()
            image_url = data.get("image_url")
            if image_url:
                persona_obj.avatar_url = image_url
                persona_obj.save(update_fields=["avatar_url"])
                logger.info(f"Successfully generated and updated avatar_url for persona {persona_id}: {image_url}")

                # Notify client via WebSocket
                ws_notify(
                    user_id=persona_obj.user_id,
                    event_type="tutor_avatar_complete",
                    title="Đã tạo xong avatar gia sư",
                    payload={
                        "persona_id": persona_id,
                        "avatar_url": image_url,
                    },
                    persist=False,
                )
                return image_url
        logger.error(f"Image service returned error {res.status_code}: {res.text}")
    except Exception as e:
        logger.error(f"Failed to call image service for persona {persona_id}: {e}", exc_info=True)

    return ""

