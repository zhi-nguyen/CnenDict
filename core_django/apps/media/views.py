import logging
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.core.cache import cache
from .tasks import get_word_by_id, generate_word_image_task, trigger_image_regeneration_task

logger = logging.getLogger(__name__)

from rest_framework.throttling import AnonRateThrottle, UserRateThrottle

class GetWordImageAnonThrottle(AnonRateThrottle):
    rate = '5/minute'

class GetWordImageUserThrottle(UserRateThrottle):
    rate = '15/minute'

class GetWordImageView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [GetWordImageAnonThrottle, GetWordImageUserThrottle]

    def get(self, request, lang, word_id):
        redis_key = f"img:{lang}:{word_id}"
        cached_data = cache.get(redis_key)
        
        # 1. Cache Hit check
        if cached_data:
            return Response(cached_data)

        # 2. Check Database
        word = get_word_by_id(word_id, lang)
        if not word:
            return Response({"detail": "Word not found"}, status=404)

        if word.image_url:
            data = {"status": "ready", "image_url": word.image_url}
            cache.set(redis_key, data, timeout=None)  # Infinite cache
            return Response(data)

        # 3. Cache Miss & DB Miss -> Return COLLECTING (Disabled auto generation)
        data = {"status": "collecting"}
        cache.set(redis_key, data, timeout=300)
        return Response(data)




class ReportInvalidImageView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = []

    def post(self, request):
        word_id = request.data.get('word_id')
        lang = request.data.get('lang', 'zh')
        if not word_id:
            return Response({"detail": "Tham số word_id không được để trống."}, status=400)

        redis_key = f"img:{lang}:{word_id}"
        lock_key = f"generating:img:{lang}:{word_id}"
        
        # CHỐT CHẶN BẢO VỆ (GUARDRAIL): Thiết lập cờ trạng thái giữ chỗ (Lock Placeholder)
        # Ngăn chặn hoàn toàn hiện tượng các requests đồng thời kích hoạt trùng tác vụ Celery
        cache.set(redis_key, {"status": "REGENERATING"}, timeout=300)
        cache.set(lock_key, True, timeout=300)

        # Đẩy tác vụ xử lý bất đồng bộ vào Celery để xóa file cũ và gọi API tái tạo ảnh mới
        user_id = str(request.user.id)
        user_tier = getattr(request.user.subscription, 'tier', 'Free') if hasattr(request.user, 'subscription') else 'Free'
        trigger_image_regeneration_task.apply_async(
            args=[str(word_id), lang, user_id],
            kwargs={'user_tier': user_tier}
        )
        
        return Response({"detail": "Hình ảnh đang được hệ thống xử lý tái tạo bất đồng bộ."}, status=202)
