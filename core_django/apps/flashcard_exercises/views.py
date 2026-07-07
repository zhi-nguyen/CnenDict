import re
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.core.cache import cache

from .models import FlashcardExercise, UserFlashcardHistory
from .tasks import generate_exercises_task, check_writing_task


class GenerateExerciseView(APIView):
    """
    GET /api/v1/flashcard/exercises/?word=学习&lang=zh
    
    1. Check DB Cache & User History -> If both reading & listening have unused cached exercises, return them.
    2. Check Redis Processing -> If PENDING, return task status.
    3. Trigger Async Celery Task -> Return PENDING.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        word = request.query_params.get('word', '').strip()
        lang = request.query_params.get('lang', 'zh').strip()

        if not word:
            return Response(
                {"error": "Query parameter 'word' is required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 1. Check DB Cache & User History
        exercises = FlashcardExercise.objects.filter(word=word, lang=lang)
        completed_ids = list(UserFlashcardHistory.objects.filter(
            user=request.user, word=word, lang=lang
        ).values_list('exercise_id', flat=True))

        unused_reading = [ex for ex in exercises if ex.exercise_type == 'reading' and ex.id not in completed_ids]
        unused_listening = [ex for ex in exercises if ex.exercise_type == 'listening' and ex.id not in completed_ids]

        if unused_reading and unused_listening:
            reading_ex = unused_reading[0]
            listening_ex = unused_listening[0]
            data = {
                'reading': {
                    'id': str(reading_ex.id),
                    'content': reading_ex.content,
                    'audio_url': reading_ex.audio_url
                },
                'listening': {
                    'id': str(listening_ex.id),
                    'content': listening_ex.content,
                    'audio_url': listening_ex.audio_url
                }
            }
            return Response({
                'status': 'SUCCESS',
                'word': word,
                'lang': lang,
                'exercises': data
            })

        # Rotate history if limit of 10 reached for either type
        reading_history_count = UserFlashcardHistory.objects.filter(
            user=request.user, word=word, lang=lang, exercise_type='reading'
        ).count()
        listening_history_count = UserFlashcardHistory.objects.filter(
            user=request.user, word=word, lang=lang, exercise_type='listening'
        ).count()
        if reading_history_count >= 10 or listening_history_count >= 10:
            UserFlashcardHistory.objects.filter(user=request.user, word=word, lang=lang).delete()
            reading_ex = exercises.filter(exercise_type='reading').first()
            listening_ex = exercises.filter(exercise_type='listening').first()
            if reading_ex and listening_ex:
                data = {
                    'reading': {
                        'id': str(reading_ex.id),
                        'content': reading_ex.content,
                        'audio_url': reading_ex.audio_url
                    },
                    'listening': {
                        'id': str(listening_ex.id),
                        'content': listening_ex.content,
                        'audio_url': listening_ex.audio_url
                    }
                }
                return Response({
                    'status': 'SUCCESS',
                    'word': word,
                    'lang': lang,
                    'exercises': data
                })

        # 2. Check Redis Processing flag
        cache_key = f"flashcard_ex:{word}:{lang}"
        processing_status = cache.get(cache_key)
        if processing_status and processing_status.get('status') == 'processing':
            return Response({
                'status': 'PENDING',
                'task_id': processing_status.get('task_id')
            }, status=status.HTTP_202_ACCEPTED)

        # 3. Trigger Async Celery Task
        user_id = str(request.user.id)
        user_tier = getattr(request.user.subscription, 'tier', 'Free') if hasattr(request.user, 'subscription') else 'Free'
        task = generate_exercises_task.apply_async(
            args=[word, lang],
            kwargs={'user_id': user_id, 'user_tier': user_tier}
        )
        
        # Save processing status for 5 minutes
        cache.set(cache_key, {'status': 'processing', 'task_id': task.id}, timeout=300)

        return Response({
            'status': 'PENDING',
            'task_id': task.id
        }, status=status.HTTP_202_ACCEPTED)


class CheckWritingView(APIView):
    """
    POST /api/v1/flashcard/check-writing/
    Body: { "sentence": "...", "target_word": "...", "lang": "zh" }
    
    Trigger grammar check by AI.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        sentence = request.data.get('sentence', '').strip()
        target_word = request.data.get('target_word', '').strip()
        lang = request.data.get('lang', 'zh').strip()

        if not sentence or not target_word:
            return Response(
                {"error": "Both 'sentence' and 'target_word' are required fields."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Language validation
        if lang == 'zh':
            if not re.search(r'[\u4e00-\u9fff]', sentence):
                return Response(
                    {"error": "Vui lòng viết câu bằng tiếng Trung (chữ Hán)."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            if re.search(r'[a-zA-Z]', sentence):
                return Response(
                    {"error": "Câu viết tiếng Trung không được chứa các từ không phải tiếng Trung (chữ Latin)."},
                    status=status.HTTP_400_BAD_REQUEST
                )
        elif lang == 'en':
            if not re.search(r'[a-zA-Z]', sentence):
                return Response(
                    {"error": "Vui lòng viết câu bằng tiếng Anh."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            if re.search(r'[\u4e00-\u9fff]', sentence):
                return Response(
                    {"error": "Câu viết tiếng Anh không được chứa chữ Trung Quốc."},
                    status=status.HTTP_400_BAD_REQUEST
                )

        user_tier = getattr(request.user.subscription, 'tier', 'Free') if hasattr(request.user, 'subscription') else 'Free'
        if user_tier == 'Free':
            return Response(
                {"error": "Writing exercise AI evaluation is only available for VIP/Premium users."},
                status=status.HTTP_403_FORBIDDEN
            )

        # Word/character count validation (limit 30)
        if lang == 'en':
            word_count = len(sentence.split())
            limit_msg = "Câu viết tiếng Anh không được vượt quá 30 từ."
        else:
            word_count = len(sentence.replace(' ', ''))
            limit_msg = "Câu viết tiếng Trung không được vượt quá 30 chữ."

        if word_count > 30:
            return Response(
                {"error": limit_msg},
                status=status.HTTP_400_BAD_REQUEST
            )

        user_id = str(request.user.id)
        task = check_writing_task.apply_async(
            args=[sentence, target_word, lang],
            kwargs={'user_id': user_id, 'user_tier': user_tier}
        )

        return Response({
            'status': 'PENDING',
            'task_id': task.id
        }, status=status.HTTP_202_ACCEPTED)


class CompleteExerciseView(APIView):
    """
    POST /api/v1/flashcard/exercises/complete/
    Body: { "exercise_id": "..." }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        exercise_id = request.data.get('exercise_id')
        if not exercise_id:
            return Response({"error": "exercise_id is required."}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            exercise = FlashcardExercise.objects.get(id=exercise_id)
        except FlashcardExercise.DoesNotExist:
            return Response({"error": "Exercise not found."}, status=status.HTTP_404_NOT_FOUND)

        history, created = UserFlashcardHistory.objects.get_or_create(
            user=request.user,
            exercise=exercise,
            defaults={
                'word': exercise.word,
                'lang': exercise.lang,
                'exercise_type': exercise.exercise_type
            }
        )

        return Response({
            "status": "SUCCESS",
            "created": created,
            "exercise_id": str(exercise.id)
        }, status=status.HTTP_200_OK)


class CheckGeneralWritingView(APIView):
    """
    POST /api/v1/flashcard/check-general-writing/
    Body: { "sentence": "...", "lang": "zh" }
    
    Trigger general writing check using AI.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        sentence = request.data.get('sentence', '').strip()
        lang = request.data.get('lang', 'zh').strip()

        if not sentence:
            return Response(
                {"error": "Field 'sentence' is required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Language validation
        if lang == 'zh':
            if not re.search(r'[\u4e00-\u9fff]', sentence):
                return Response(
                    {"error": "Vui lòng viết đoạn văn bằng tiếng Trung (chữ Hán)."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            if re.search(r'[a-zA-Z]', sentence):
                return Response(
                    {"error": "Đoạn văn viết tiếng Trung không được chứa các từ không phải tiếng Trung (chữ Latin)."},
                    status=status.HTTP_400_BAD_REQUEST
                )
        elif lang == 'en':
            if not re.search(r'[a-zA-Z]', sentence):
                return Response(
                    {"error": "Vui lòng viết đoạn văn bằng tiếng Anh."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            if re.search(r'[\u4e00-\u9fff]', sentence):
                return Response(
                    {"error": "Đoạn văn viết tiếng Anh không được chứa chữ Trung Quốc."},
                    status=status.HTTP_400_BAD_REQUEST
                )

        user_tier = getattr(request.user.subscription, 'tier', 'Free') if hasattr(request.user, 'subscription') else 'Free'
        if user_tier == 'Free':
            return Response(
                {"error": "Writing evaluation is only available for VIP/Premium users."},
                status=status.HTTP_403_FORBIDDEN
            )

        try:
            from apps.core_shared.ai_client import get_genai_client
            from google.genai import errors

            client = get_genai_client()
            
            # System prompt and user prompt
            lang_name = "tiếng Trung" if lang == "zh" else "tiếng Anh"
            system_instruction = f"""Bạn là một trợ lý AI giáo dục chấm bài viết của học sinh bằng {lang_name}.
Nhiệm vụ của bạn là kiểm tra xem đoạn văn/câu do học sinh tự viết có viết đúng ngữ pháp hay không, đánh giá từ vựng, ngữ pháp và sự mạch lạc.
Bạn phải trả về một đối tượng JSON hợp lệ duy nhất có cấu trúc sau, không kèm bất kỳ giải thích nào khác ngoài JSON:

{{
  "score": 85, // Điểm số từ 0 đến 100
  "is_correct": true, // true nếu đúng ngữ pháp hoàn toàn hoặc chỉ có lỗi cực nhỏ, false nếu sai ngữ pháp nghiêm trọng
  "feedback": "Nhận xét chi tiết bằng tiếng Việt về đoạn văn viết của học sinh, chỉ ra các lỗi sai ngữ pháp, từ vựng hoặc cách diễn đạt nếu có.",
  "suggestion": "Đoạn văn gợi ý viết lại chuẩn xác và tự nhiên hơn."
}}
"""
            prompt = f"Ngôn ngữ: '{lang_name}'. Bài viết của học sinh: '{sentence}'."

            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config={
                    'system_instruction': system_instruction,
                    'response_mime_type': 'application/json'
                }
            )

            raw_text = response.text
            from .tasks import clean_json_string
            cleaned_text = clean_json_string(raw_text)
            
            # Load as JSON to ensure validity
            import json
            result_data = json.loads(cleaned_text)

            return Response({
                'status': 'SUCCESS',
                'result': result_data
            }, status=status.HTTP_200_OK)

        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error in CheckGeneralWritingView: {e}")
            return Response(
                {"error": "Failed to evaluate writing exercise."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
