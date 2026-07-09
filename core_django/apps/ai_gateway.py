import re
import logging
import hashlib
from rest_framework.response import Response
from rest_framework import status
from django.core.cache import cache

logger = logging.getLogger(__name__)


class AIFallbackGateway:
    @staticmethod
    def get_client_ip(request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR', 'anonymous')

    @staticmethod
    def call_gcp_translation_v3(text, direction):
        import google.auth
        from google.auth.transport.requests import Request as AuthRequest
        import requests
        import os

        # Map direction to Google Cloud Translation source and target codes
        if direction == 'zh_vi':
            sl, tl = 'zh', 'vi'
        elif direction == 'vi_zh':
            sl, tl = 'vi', 'zh'
        elif direction == 'en_vi':
            sl, tl = 'en', 'vi'
        elif direction == 'vi_en':
            sl, tl = 'vi', 'en'
        else:
            sl, tl = 'auto', 'vi'

        project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "project-99192cc3-792c-4507-b70")
        
        credentials, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/cloud-platform'])
        auth_req = AuthRequest()
        credentials.refresh(auth_req)

        url = f"https://translate.googleapis.com/v3/projects/{project_id}/locations/global:translateText"
        headers = {
            "Authorization": f"Bearer {credentials.token}",
            "Content-Type": "application/json"
        }
        payload = {
            "contents": [text],
            "targetLanguageCode": tl,
            "sourceLanguageCode": sl,
            "mimeType": "text/plain"
        }
        response = requests.post(url, json=payload, headers=headers, timeout=5)
        response.raise_for_status()
        data = response.json()
        translated_text = "".join([t["translatedText"] for t in data.get("translations", [])])
        return translated_text

    @staticmethod
    def get_translation_char_limit(user, mode='zh'):
        """
        Lấy hạn mức ký tự dịch thuật dựa theo gói tài khoản.
        - zh: đếm ký tự tiếng Trung (ngắn hơn)
        - en: đếm ký tự tiếng Anh/Việt (dài hơn)
        """
        if not user or not user.is_authenticated:
            tier = 'Guest'
        else:
            try:
                tier = user.subscription.tier if hasattr(user, 'subscription') else 'Free'
            except Exception:
                tier = 'Free'
            
        # Truy vấn cấu hình từ DB
        from apps.subscriptions.models import VolumeLimitConfig
        try:
            config = VolumeLimitConfig.objects.filter(tier__iexact=tier).first()
            if config:
                return config.translation_zh_limit if mode == 'zh' else config.translation_en_limit
        except Exception:
            pass

        # Fallback values if DB lookup fails
        tier_lower = tier.lower()
        if tier_lower == 'guest':
            return 150 if mode == 'zh' else 300
        elif tier_lower == 'plus':
            return 1000 if mode == 'zh' else 2000
        elif tier_lower == 'pro':
            return 2000 if mode == 'zh' else 4000
        elif tier_lower == 'premium':
            return 3000 if mode == 'zh' else 6000
        else: # Free
            return 500 if mode == 'zh' else 1000

    @staticmethod
    def count_words(text, mode='zh'):
        """
        Đếm số ký tự của văn bản (đã chuyển sang dùng đếm ký tự cho mọi ngôn ngữ).
        """
        if not text:
            return 0
        return len(text)

    @classmethod
    def handle_search_fallback(cls, request, query, db_lookup_func, task_func, cache_key_prefix="ai_trans", mode='zh'):
        """
        Logic điều phối phòng thủ chung cho API Tìm kiếm.
        """
        query_len = cls.count_words(query, mode=mode)
        max_limit = 100 if mode == 'zh' else 30 # Giới hạn từ khóa tìm kiếm: 100 kí tự (zh) hoặc 30 từ (en)

        if query_len > max_limit:
            msg = f"Từ khóa vượt quá độ dài cho phép ({max_limit} {'ký tự' if mode == 'zh' else 'từ'})."
            return Response({"detail": msg}, status=status.HTTP_400_BAD_REQUEST)

        # Chạy hàm callback để kiểm tra DB Hit & Lưu dữ liệu vào closure container
        db_hit = db_lookup_func()

        if query and not db_hit:
            # 1. Xác định hướng dịch thuật (direction)
            if mode == 'en':
                direction = 'vi_en'
            else: # mode == 'zh'
                import re
                has_latin = bool(re.search(r'[a-zA-Z]', query))
                has_chinese = bool(re.search(r'[\u4e00-\u9fff]', query))
                if has_chinese and not has_latin:
                    direction = 'zh_vi'
                else:
                    direction = 'vi_zh'

            # Tra cứu bộ nhớ đệm AI (Redis Cache)
            import hashlib
            hashed_query = hashlib.md5(query.encode('utf-8')).hexdigest()
            ai_cache_key = f"{cache_key_prefix}:{direction}:{hashed_query}"
            cached_data = cache.get(ai_cache_key)

            if cached_data:
                if cached_data.get('status') == 'success':
                    return Response(cached_data['result'])
                if cached_data.get('status') == 'processing':
                    return Response({"status": "PENDING", "task_id": cached_data['task_id']}, status=status.HTTP_202_ACCEPTED)

            # Khống chế giới hạn Conditional Rate Limit theo Tier tài khoản (Tránh throttling khi tìm kiếm chuỗi ký tự dài)
            user = request.user
            if not user or not user.is_authenticated:
                ai_limit = 15  # Guest: 15 lần/phút
                user_tier = 'Guest'
            else:
                try:
                    user_tier = user.subscription.tier if hasattr(user, 'subscription') else 'Free'
                except Exception:
                    user_tier = 'Free'
                
                tier_lower = user_tier.lower()
                if tier_lower == 'plus':
                    ai_limit = 60   # Plus: 60 lần/phút
                elif tier_lower == 'pro':
                    ai_limit = 100  # Pro: 100 lần/phút
                elif tier_lower == 'premium':
                    ai_limit = 120  # Premium: 120 lần/phút
                else:
                    ai_limit = 30   # Free: 30 lần/phút

            ident = f"user_{user.id}" if user and user.is_authenticated else f"ip_{cls.get_client_ip(request)}"
            ai_throttle_key = f"throttle:ai_fallback:{ident}"
            
            try:
                redis_client = cache.client.get_client()
                current_ai_requests = redis_client.incr(ai_throttle_key)
                if current_ai_requests == 1:
                    redis_client.expire(ai_throttle_key, 60)
            except Exception:
                current_ai_requests = cache.get(ai_throttle_key, 0) + 1
                cache.set(ai_throttle_key, current_ai_requests, timeout=60)

            if current_ai_requests > ai_limit:
                return Response(
                    {"detail": f"Tài khoản đã vượt định mức dịch thuật bằng AI của gói hiện tại ({ai_limit} lần/phút). Vui lòng thử lại sau ít phút."}, 
                    status=status.HTTP_429_TOO_MANY_REQUESTS
                )

            # Chặn user Guest/Free dùng AI Fallback Celery task, chuyển hướng sang Google Translate v3 đồng bộ
            if user_tier.lower() in ['guest', 'free']:
                try:
                    translated_text = cls.call_gcp_translation_v3(query, direction)
                    result = {
                        'translatedText': translated_text,
                        'source': 'google_translate',
                        'status': 'SUCCESS'
                    }
                    # Cache kết quả Google Translate trong 3 ngày
                    cache.set(ai_cache_key, {"status": "success", "result": result}, timeout=3 * 24 * 60 * 60)
                    return Response(result, status=status.HTTP_200_OK)
                except Exception as e:
                    logger.error(f"Google Cloud Translation v3 failed in search fallback: {e}")
                    return Response({
                        "error": f"Dịch vụ Google Cloud Translation tạm thời gặp sự cố: {str(e)}"
                    }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            # Kích hoạt Celery Task dịch thuật (chỉ dành cho VIPs)
            guest_id = request.data.get("guest_id") or request.query_params.get("guest_id")
            effective_user_id = str(user.id) if user.is_authenticated else guest_id

            if not effective_user_id:
                logger.warning(
                    f"⚠️ No user_id or guest_id found for AI search fallback task (query: {query}). "
                    "WebSocket notification will NOT be sent."
                )

            task_kwargs = {"user_id": effective_user_id} if effective_user_id else {}
            task_kwargs["user_tier"] = user_tier
            task_kwargs["direction"] = direction

            task = task_func.apply_async(
                args=[query], 
                kwargs=task_kwargs
            )

            # Thiết lập trạng thái xử lý ngầm (chống Cache Stampede)
            cache.set(ai_cache_key, {"status": "processing", "task_id": task.id}, timeout=5 * 60)

            return Response({"task_id": task.id}, status=status.HTTP_202_ACCEPTED)

        return None

    @classmethod
    def handle_translation_fallback(cls, request, task_func, cache_key_prefix="ai_trans", mode='zh'):
        """
        Logic điều phối phòng thủ chung cho API Dịch thuật.
        """
        # Safeguard: Check Content-Length to prevent memory exhaustion (413 Payload Too Large)
        content_length = request.META.get('CONTENT_LENGTH')
        if content_length:
            try:
                # 150KB limit is extremely generous for normal translation texts (approx. 50k characters)
                if int(content_length) > 150 * 1024:
                    return Response({
                        "error": "Request Entity Too Large",
                        "detail": "Văn bản gửi lên vượt quá giới hạn dung lượng cho phép (tối đa 150KB)."
                    }, status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
            except ValueError:
                pass

        text_input = request.data.get("text", "").strip()
        if not text_input:
            return Response({'error': 'No text provided'}, status=status.HTTP_400_BAD_REQUEST)
        
        direction = request.data.get("direction")
        if not direction:
            direction = "zh_vi" if mode == 'zh' else "en_vi"
        
        input_mode = 'en' if direction.startswith('vi_') else mode
        limit = cls.get_translation_char_limit(request.user, mode=input_mode)
        text_len = cls.count_words(text_input, mode=input_mode)
        
        if text_len > limit:
            unit = "ký tự" if input_mode == 'zh' else "từ"
            msg = f"Độ dài văn bản vượt quá hạn mức cho phép của tài khoản ({limit} {unit})."
            return Response({
                "detail": msg,
                "error": msg
            }, status=status.HTTP_400_BAD_REQUEST)

        # ── Tầng 0: Tra cứu cơ sở dữ liệu đồng bộ (Chỉ áp dụng khi dịch sang Tiếng Việt) ──
        if direction in ['zh_vi', 'en_vi']:
            q_lower = text_input.lower().strip()
            
            if mode == 'zh':
                from apps.dictionary_zh.models import ZhWord, ZhExample
                from django.db.models import Q
                
                cleaned_query = re.sub(r'[。，、！？. , ! ?]+$', '', q_lower)
                if cleaned_query:
                    # 1. Check ZhExample (exact example match)
                    regex_pattern = r'^' + re.escape(cleaned_query) + r'[。，、！？. , ! ?]*$'
                    match = ZhExample.objects.filter(chinese__iregex=regex_pattern).first()
                    if match:
                        return Response({
                            'translatedText': match.vietnamese,
                            'source': 'database',
                            'status': 'SUCCESS'
                        }, status=status.HTTP_200_OK)
                    
                    # 2. Check ZhWord (dictionary word match)
                    word_match = ZhWord.objects.filter(Q(word=cleaned_query) | Q(traditional=cleaned_query)).first()
                    if word_match:
                        return Response({
                            'translatedText': word_match.translation_vi,
                            'source': 'database',
                            'status': 'SUCCESS'
                        }, status=status.HTTP_200_OK)
                        
            elif mode == 'en':
                from apps.dictionary_en.models import EnWord, EnExample
                
                cleaned_query = re.sub(r'[. , ! ?]+$', '', q_lower)
                if cleaned_query:
                    # 1. Check EnExample
                    match = EnExample.objects.filter(english__iexact=cleaned_query).first()
                    if match:
                        return Response({
                            'translatedText': match.vietnamese,
                            'source': 'database',
                            'status': 'SUCCESS'
                        }, status=status.HTTP_200_OK)
                    
                    # 2. Check EnWord
                    word_match = EnWord.objects.filter(word__iexact=cleaned_query).first()
                    if word_match:
                        return Response({
                            'translatedText': word_match.translation_vi,
                            'source': 'database',
                            'status': 'SUCCESS'
                        }, status=status.HTTP_200_OK)

        # Determine user tier for SLA routing
        user = request.user
        if user and user.is_authenticated:
            user_tier = getattr(user.subscription, 'tier', 'Free') if hasattr(user, 'subscription') else 'Free'
        else:
            user_tier = 'Guest'

        # Get translation engine option (default is AI)
        engine = request.data.get("engine", "ai")
        # Enforce google engine for Guest and Free users
        if user_tier.lower() in ['guest', 'free']:
            engine = 'google'

        hashed_text = hashlib.md5(text_input.encode('utf-8')).hexdigest()
        ai_cache_key = f"{cache_key_prefix}:{direction}:{hashed_text}"
        cached_data = cache.get(ai_cache_key)

        if cached_data:
            # Overwrite cache bypass: if engine is explicitly 'ai' but cache was Google Translate, we bypass the cache hit
            if engine == 'ai' and cached_data.get('result', {}).get('source') == 'google_translate':
                pass
            else:
                if cached_data.get('status') == 'success':
                    return Response(cached_data['result'])
                if cached_data.get('status') == 'processing':
                    return Response({"status": "PENDING", "task_id": cached_data['task_id']}, status=status.HTTP_202_ACCEPTED)

        # ── Tầng 2: Kiểm soát Tốc độ gọi dịch thuật thực tế (Rate Limit) ──
        if user_tier.lower() == 'guest':
            trans_limit = 10  # Guest: 10 lần/phút
        elif user_tier.lower() == 'free':
            trans_limit = 20  # Free: 20 lần/phút
        elif user_tier.lower() == 'plus':
            trans_limit = 45  # Plus: 45 lần/phút
        else:
            trans_limit = 90  # Pro, Premium: 90 lần/phút

        ident = f"user_{user.id}" if user and user.is_authenticated else f"ip_{cls.get_client_ip(request)}"
        trans_throttle_key = f"throttle:trans_fallback:{ident}"
        
        try:
            redis_client = cache.client.get_client()
            current_trans_requests = redis_client.incr(trans_throttle_key)
            if current_trans_requests == 1:
                redis_client.expire(trans_throttle_key, 60)
        except Exception:
            current_trans_requests = cache.get(trans_throttle_key, 0) + 1
            cache.set(trans_throttle_key, current_trans_requests, timeout=60)

        if current_trans_requests > trans_limit:
            return Response(
                {"detail": f"Bạn đã vượt quá giới hạn dịch thuật ({trans_limit} lần/phút). Vui lòng thử lại sau ít phút."}, 
                status=status.HTTP_429_TOO_MANY_REQUESTS
            )

        # Handle Google Cloud Translation v3 synchronously and cache it
        if engine == 'google':
            try:
                translated_text = cls.call_gcp_translation_v3(text_input, direction)
                result = {
                    'translatedText': translated_text,
                    'source': 'google_translate',
                    'status': 'SUCCESS'
                }
                # Cache the Google Translate result for 3 days
                cache.set(ai_cache_key, {"status": "success", "result": result}, timeout=3 * 24 * 60 * 60)
                return Response(result, status=status.HTTP_200_OK)
            except Exception as e:
                logger.error(f"Google Cloud Translation v3 failed: {e}")
                return Response({
                    "error": f"Dịch vụ Google Cloud Translation tạm thời gặp sự cố: {str(e)}"
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # Trigger Gemini AI Celery Task for VIPs
        guest_id = request.data.get("guest_id") or request.query_params.get("guest_id")
        effective_user_id = str(user.id) if user.is_authenticated else guest_id

        if not effective_user_id:
            logger.warning(
                f"⚠️ No user_id or guest_id found for AI translation fallback task (input: {text_input[:20]}...). "
                "WebSocket notification will NOT be sent."
            )

        task_kwargs = {
            "user_id": effective_user_id,
            "direction": direction
        } if effective_user_id else {"direction": direction}
        task_kwargs["user_tier"] = user_tier

        task = task_func.apply_async(
            args=[text_input], 
            kwargs=task_kwargs
        )
        cache.set(ai_cache_key, {"status": "processing", "task_id": task.id}, timeout=5 * 60)
        
        return Response({
            "status": "PENDING",
            "task_id": task.id
        }, status=status.HTTP_202_ACCEPTED)
