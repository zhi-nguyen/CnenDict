import hashlib
import uuid
import logging
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework import status
from django.core.cache import cache

from .tts_tasks import generate_tts_audio_task

logger = logging.getLogger(__name__)

class TriggerTTSView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, *args, **kwargs):
        text = request.query_params.get('text', '').strip()
        voice = request.query_params.get('voice', '').strip()

        if not text or not voice:
            return Response(
                {"error": "Both 'text' and 'voice' query parameters are required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Validate text length based on language
        has_chinese = any('\u4e00' <= char <= '\u9fff' for char in text)
        if has_chinese:
            # Chinese character limit
            if len(text) > 200:
                return Response(
                    {"error": "Độ dài văn bản phát âm tiếng Trung không được vượt quá 200 ký tự."},
                    status=status.HTTP_400_BAD_REQUEST
                )
        else:
            # English word limit
            word_count = len(text.split())
            if word_count > 200:
                return Response(
                    {"error": "Độ dài văn bản phát âm tiếng Anh không được vượt quá 200 từ."},
                    status=status.HTTP_400_BAD_REQUEST
                )

        # 1. Compute MD5 cache key
        text_hash = hashlib.md5(f"{text}:{voice}".encode('utf-8')).hexdigest()
        cache_key = f"tts:audio:{text_hash}"

        # 2. Check if the audio is already generated and cached
        cached_url = cache.get(cache_key)
        if cached_url:
            return Response(
                {
                    "status": "SUCCESS",
                    "audio_url": cached_url,
                    "text": text,
                    "voice": voice
                },
                status=status.HTTP_200_OK
            )

        # 2b. Check if a task is already pending for this text+voice
        pending_key = f"tts:pending:{text_hash}"
        existing_task_id = cache.get(pending_key)
        if existing_task_id:
            logger.info(f"TTS dedup: reusing pending task {existing_task_id} for text_hash={text_hash}")
            return Response(
                {
                    "status": "PENDING",
                    "task_id": existing_task_id,
                    "text": text,
                    "voice": voice
                },
                status=status.HTTP_202_ACCEPTED
            )

        # 3. Resolve user_id / guest_id for WebSocket routing
        if request.user.is_authenticated:
            user_id = str(request.user.id)
            user_tier = getattr(request.user.subscription, 'tier', 'Free') if hasattr(request.user, 'subscription') else 'Free'
        else:
            user_id = request.headers.get('X-Guest-ID') or request.query_params.get('guest_id')
            if not user_id:
                user_id = f"guest_{uuid.uuid4()}"
            user_tier = 'Guest'

        # 4. Trigger Celery background task
        task_id = str(uuid.uuid4())
        cache.set(pending_key, task_id, timeout=30)  # 30s dedup window
        generate_tts_audio_task.apply_async(
            kwargs={
                'task_id': task_id,
                'user_id': user_id,
                'text': text,
                'voice': voice,
                'cache_key': cache_key,
                'user_tier': user_tier
            }
        )

        logger.info(f"Enqueued async TTS task {task_id} for user {user_id}. Text length: {len(text)}")

        return Response(
            {
                "status": "PENDING",
                "task_id": task_id,
                "text": text,
                "voice": voice
            },
            status=status.HTTP_202_ACCEPTED
        )


class BatchTTSStatusView(APIView):
    """
    POST /api/core/media/tts/batch-status/
    
    Kiểm tra hàng loạt từ nào đã có TTS audio trong Redis cache.
    Frontend dùng kết quả này để chỉ gọi prefetchTTS cho các từ chưa cached.
    """
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        items = request.data.get('items', [])

        if not items or not isinstance(items, list):
            return Response(
                {"error": "'items' must be a non-empty list."},
                status=status.HTTP_400_BAD_REQUEST
            )

        MAX_BATCH_SIZE = 50
        if len(items) > MAX_BATCH_SIZE:
            return Response(
                {"error": f"Batch size must not exceed {MAX_BATCH_SIZE} items."},
                status=status.HTTP_400_BAD_REQUEST
            )

        results = []
        # Build all cache keys, then use cache.get_many() for single Redis MGET roundtrip
        key_map = {}  # cache_key -> item
        for item in items:
            text = (item.get('text') or '').strip()
            voice = (item.get('voice') or '').strip()
            if not text or not voice:
                results.append({"text": text, "status": "invalid"})
                continue
            text_hash = hashlib.md5(f"{text}:{voice}".encode('utf-8')).hexdigest()
            cache_key = f"tts:audio:{text_hash}"
            key_map[cache_key] = {"text": text, "voice": voice}

        # Single MGET roundtrip to Redis
        cached_values = cache.get_many(list(key_map.keys()))

        for cache_key, item_info in key_map.items():
            audio_url = cached_values.get(cache_key)
            if audio_url:
                results.append({
                    "text": item_info["text"],
                    "status": "cached",
                    "audio_url": audio_url
                })
            else:
                results.append({
                    "text": item_info["text"],
                    "status": "missing"
                })

        return Response({"results": results}, status=status.HTTP_200_OK)


class BatchTriggerTTSView(APIView):
    """
    POST /api/core/media/tts/batch-trigger/
    
    Kiểm tra và kích hoạt hàng loạt sinh giọng nói (TTS) cho danh sách từ vựng.
    - Nếu đã có cached -> trả về cached status kèm audio_url.
    - Nếu đang pending -> trả về pending status kèm task_id (reuse).
    - Nếu chưa có -> trigger Celery task -> trả về pending status kèm task_id mới.
    """
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        items = request.data.get('items', [])

        if not items or not isinstance(items, list):
            return Response(
                {"error": "'items' must be a non-empty list."},
                status=status.HTTP_400_BAD_REQUEST
            )

        MAX_BATCH_SIZE = 50
        if len(items) > MAX_BATCH_SIZE:
            return Response(
                {"error": f"Batch size must not exceed {MAX_BATCH_SIZE} items."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Resolve user_id and user_tier for WebSocket routing (same as TriggerTTSView)
        if request.user.is_authenticated:
            user_id = str(request.user.id)
            user_tier = getattr(request.user.subscription, 'tier', 'Free') if hasattr(request.user, 'subscription') else 'Free'
        else:
            user_id = request.headers.get('X-Guest-ID') or request.query_params.get('guest_id')
            if not user_id:
                user_id = f"guest_{uuid.uuid4()}"
            user_tier = 'Guest'

        results = []
        # Build all cache keys
        key_map = {}  # cache_key -> item
        for item in items:
            text = (item.get('text') or '').strip()
            voice = (item.get('voice') or '').strip()
            if not text or not voice:
                results.append({"text": text, "status": "invalid"})
                continue
            text_hash = hashlib.md5(f"{text}:{voice}".encode('utf-8')).hexdigest()
            cache_key = f"tts:audio:{text_hash}"
            key_map[cache_key] = {"text": text, "voice": voice, "text_hash": text_hash}

        # Single MGET to check cache
        cached_values = cache.get_many(list(key_map.keys()))

        # For missing ones, check pending keys
        pending_check_keys = []
        for cache_key, item_info in key_map.items():
            if not cached_values.get(cache_key):
                pending_check_keys.append(f"tts:pending:{item_info['text_hash']}")

        pending_values = cache.get_many(pending_check_keys) if pending_check_keys else {}

        # Loop through all and build results, triggering tasks for missing + non-pending ones
        for cache_key, item_info in key_map.items():
            audio_url = cached_values.get(cache_key)
            if audio_url:
                results.append({
                    "text": item_info["text"],
                    "status": "cached",
                    "audio_url": audio_url
                })
                continue

            text = item_info["text"]
            voice = item_info["voice"]
            text_hash = item_info["text_hash"]
            pending_key = f"tts:pending:{text_hash}"
            
            existing_task_id = pending_values.get(pending_key)
            if existing_task_id:
                results.append({
                    "text": text,
                    "status": "pending",
                    "task_id": existing_task_id
                })
                continue

            # Not cached and not pending -> trigger a new task
            task_id = str(uuid.uuid4())
            cache.set(pending_key, task_id, timeout=30)  # 30s dedup window
            generate_tts_audio_task.apply_async(
                kwargs={
                    'task_id': task_id,
                    'user_id': user_id,
                    'text': text,
                    'voice': voice,
                    'cache_key': cache_key,
                    'user_tier': user_tier
                }
            )
            logger.info(f"Batch trigger: enqueued async TTS task {task_id} for user {user_id}. Text: {text[:20]}")
            results.append({
                "text": text,
                "status": "pending",
                "task_id": task_id
            })

        return Response({"results": results}, status=status.HTTP_200_OK)

