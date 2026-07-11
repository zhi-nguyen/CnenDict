import json
import logging
from celery import shared_task
from core_project.ws_utils import get_redis_client

logger = logging.getLogger(__name__)


@shared_task
def persist_chat_messages(user_id: str, messages: list) -> bool:
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
        chat_messages.append(
            ChatMessage(
                user=user,
                role=msg.get("role", "user"),
                content=msg.get("content", ""),
            )
        )

    if chat_messages:
        try:
            ChatMessage.objects.bulk_create(chat_messages)
            logger.info(f"Persisted {len(chat_messages)} messages to DB for user {user_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to bulk create ChatMessage: {e}")
            return False
    return False


@shared_task(queue='queue_chat')
def dispatch_chat_request(user_id, user_text, user_role, user_level, topic, user_name, **kwargs):
    """
    Celery task to dispatch a chat request to Redis Pub/Sub.
    1. Increments chat:counter:{user_id}
    2. Trims active chat history in Redis to 10 messages (persisting overflow to DB)
    3. If counter > 10, queries pgvector to get past context related to the user's input
    4. If counter % 6 == 0, dispatches async_summarize_and_embed for the last 6 messages
    5. Publishes complete payload (with user_text and past_context) to Redis channel
    """
    try:
        redis_client = get_redis_client()
        from django.conf import settings as django_settings

        user_id_str = str(user_id)

        # 1. State Counter
        counter_key = f"chat:counter:{user_id_str}"
        counter = redis_client.incr(counter_key)
        redis_client.expire(counter_key, 30 * 24 * 60 * 60)  # 30 days

        # 2. Check and persist chat history exceeding 20 messages (10 turns)
        redis_key = f"chat:history:{user_id_str}"
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
                    persist_chat_messages.delay(user_id_str, popped_messages)
        except Exception as trim_err:
            logger.error(f"Failed to check/trim chat history in Redis for user {user_id_str}: {trim_err}")

        # 3. Retrieve past context via RAG if counter > threshold
        past_context = ""
        if counter > django_settings.CHAT_RAG_THRESHOLD:
            try:
                past_context = _retrieve_rag_context(user_id_str, user_text)
            except Exception as rag_err:
                logger.error(f"Failed to retrieve RAG context for user {user_id_str}: {rag_err}", exc_info=True)

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
                    async_summarize_and_embed.delay(user_id_str, messages)
            except Exception as sum_err:
                logger.error(f"Failed to trigger summarization for user {user_id_str}: {sum_err}")

        # 5. Publish the chat request with past context to Redis for FastAPI service
        channel = f"ai:chat:request:{user_id_str}"
        payload = {
            "user_id": user_id_str,
            "user_text": user_text,
            "user_role": user_role,
            "user_level": user_level,
            "topic": topic,
            "user_name": user_name,
            "past_context": past_context,
            "learning_language": kwargs.get("learning_language", "zh"),
            "context_setting": kwargs.get("context_setting", "wuxia"),
        }
        redis_client.publish(channel, json.dumps(payload, ensure_ascii=False))
        logger.info(f"Dispatched chat request for user {user_id_str} with RAG context: bool({bool(past_context)}) and language: {payload['learning_language']}, setting: {payload['context_setting']}")
        return True
    except Exception as e:
        logger.error(f"Failed to dispatch chat request: {e}", exc_info=True)
        return False


@shared_task(bind=True, max_retries=2, default_retry_delay=30, queue='queue_chat')
def async_summarize_and_embed(self, user_id: str, messages: list) -> bool:
    """
    Asynchronous Celery pipeline to:
    1. Summarize conversation via Gemini model
    2. Vectorize the summary using text-embedding-004
    3. Save the result to ChatSummary table in PostgreSQL
    """
    from django.conf import settings as django_settings
    from django.contrib.auth import get_user_model
    from .models import ChatSummary
    from google import genai

    logger.info(f"Starting async_summarize_and_embed for user {user_id} with {len(messages)} messages")
    
    User = get_user_model()
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        logger.error(f"User {user_id} does not exist. Cannot save summary.")
        return False

    try:
        # Initialize Gemini Client via Vertex AI
        client = genai.Client(vertexai=True, location="global")

        # 1. Summarization prompt
        conv_text = "\n".join([f"{m.get('role', 'user')}: {m.get('content', '')}" for m in messages])
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
        logger.info(f"Generating embedding for summary of user {user_id}")
        embed_resp = client.models.embed_content(
            model=django_settings.GEMINI_EMBEDDING_MODEL,
            contents=summary_text,
        )
        embedding_values = embed_resp.embeddings[0].values  # List[float] (768 dimensions)

        # 3. Store to PostgreSQL
        ChatSummary.objects.create(
            user=user,
            summary_text=summary_text,
            embedding=embedding_values,
            message_count=len(messages),
        )
        logger.info(f"Successfully saved ChatSummary for user {user_id}")
        return True

    except Exception as e:
        logger.error(f"Error in async_summarize_and_embed for user {user_id}: {e}", exc_info=True)
        try:
            self.retry(exc=e)
        except Exception:
            pass
        return False


def _retrieve_rag_context(user_id: str, query_text: str) -> str:
    """
    Synchronous helper to retrieve relevant past summaries using cosine similarity.
    """
    from django.conf import settings as django_settings
    from .models import ChatSummary
    from pgvector.django import CosineDistance
    from google import genai

    if not query_text.strip():
        return ""

    logger.info(f"Retrieving RAG context for user {user_id}")
    
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
        .filter(user_id=user_id)
        .annotate(distance=CosineDistance("embedding", query_vector))
        .order_by("distance")
        [:django_settings.CHAT_RAG_TOP_K]
    )

    valid_summaries = [s for s in summaries if s.distance is not None and s.distance < 0.6] # similarity threshold of ~0.4+ (distance < 0.6)
    if not valid_summaries:
        logger.info(f"No relevant past context found for user {user_id} (top distance: {summaries[0].distance if summaries else 'N/A'})")
        return ""

    # 3. Format context
    context_lines = [f"- {s.summary_text}" for s in valid_summaries]
    logger.info(f"Found {len(context_lines)} relevant past summaries for user {user_id}")
    return (
        "Đây là ngữ cảnh từ các cuộc trò chuyện trước đó với người dùng:\n"
        + "\n".join(context_lines)
    )

