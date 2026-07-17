import re
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.core.cache import cache
from django.shortcuts import get_object_or_404

from .models import FlashcardExercise, UserFlashcardHistory, WritingTask
from .tasks import generate_exercises_task, check_writing_task, check_general_writing_task


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

        user_tier = getattr(request.user.subscription, 'tier', 'Free') if hasattr(request.user, 'subscription') else 'Free'
        from apps.gamification.coin_service import CoinService, InsufficientCoinsError
        config = CoinService.get_coin_config(user_tier)
        
        # Calculate cost based on length
        if lang == 'zh':
            length = len(sentence.replace(' ', ''))
            base_cost = config.writing_base_cost_zh if config else 1
            increment_cost = config.writing_increment_cost_zh if config else 1
        else:
            length = len(sentence.split())
            base_cost = config.writing_base_cost_en if config else 1
            increment_cost = config.writing_increment_cost_en if config else 1
            
        cost = base_cost
        if length >= 50:
            cost += ((length - 50) // 50 + 1) * increment_cost

        # Try to spend coins if cost > 0
        if cost > 0:
            try:
                CoinService.spend_coins(
                    user=request.user,
                    lang=lang,
                    amount=cost,
                    transaction_type='SPEND_WRITING_PRACTICE',
                    note=f"Luyện viết sâu AI: {sentence[:30]}..."
                )
            except InsufficientCoinsError:
                lang_name = "Linh Thạch" if lang == "zh" else "Coin"
                return Response(
                    {"error": f"Không đủ {lang_name} để kiểm tra bài viết (Cần {cost} {lang_name}). Hãy tích lũy thêm điểm!"},
                    status=status.HTTP_402_PAYMENT_REQUIRED
                )

        # Create WritingTask database log entry
        task_obj = WritingTask.objects.create(
            user=request.user,
            task_type='deep_practice',
            sentence=sentence,
            target_word=target_word,
            lang=lang,
            status='PENDING',
            cost=cost
        )

        user_id = str(request.user.id)
        task = check_writing_task.apply_async(
            args=[sentence, target_word, lang],
            kwargs={
                'user_id': user_id, 
                'cost': cost,
                'writing_task_id': str(task_obj.id)
            }
        )

        return Response({
            'status': 'PENDING',
            'task_id': str(task_obj.id)
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
        from apps.gamification.coin_service import CoinService, InsufficientCoinsError
        config = CoinService.get_coin_config(user_tier)
        
        # Calculate cost based on length
        if lang == 'zh':
            length = len(sentence.replace(' ', ''))
            base_cost = config.writing_base_cost_zh if config else 1
            increment_cost = config.writing_increment_cost_zh if config else 1
        else:
            length = len(sentence.split())
            base_cost = config.writing_base_cost_en if config else 1
            increment_cost = config.writing_increment_cost_en if config else 1
            
        cost = base_cost
        if length >= 50:
            cost += ((length - 50) // 50 + 1) * increment_cost

        # Try to spend coins if cost > 0
        if cost > 0:
            try:
                CoinService.spend_coins(
                    user=request.user,
                    lang=lang,
                    amount=cost,
                    transaction_type='SPEND_WRITING_PRACTICE',
                    note=f"Luyện viết tự do AI: {sentence[:30]}..."
                )
            except InsufficientCoinsError:
                lang_name = "Linh Thạch" if lang == "zh" else "Coin"
                return Response(
                    {"error": f"Không đủ {lang_name} để chấm điểm bài viết này (Cần {cost} {lang_name}). Hãy tích lũy thêm điểm!"},
                    status=status.HTTP_402_PAYMENT_REQUIRED
                )

        # Create WritingTask database log entry
        task_obj = WritingTask.objects.create(
            user=request.user,
            task_type='general',
            sentence=sentence,
            lang=lang,
            status='PENDING',
            cost=cost
        )

        user_id = str(request.user.id)
        task = check_general_writing_task.apply_async(
            args=[sentence, lang],
            kwargs={
                'user_id': user_id, 
                'cost': cost,
                'writing_task_id': str(task_obj.id)
            }
        )

        return Response({
            'status': 'PENDING',
            'task_id': str(task_obj.id)
        }, status=status.HTTP_202_ACCEPTED)


class PendingWritingTasksView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        lang = request.query_params.get('lang', '').strip()
        task_type = request.query_params.get('task_type', '').strip()

        pending_tasks = WritingTask.objects.filter(user=request.user, status='PENDING')
        if lang:
            pending_tasks = pending_tasks.filter(lang=lang)
        if task_type:
            pending_tasks = pending_tasks.filter(task_type=task_type)

        task = pending_tasks.order_by('-created_at').first()
        if task:
            return Response({
                'has_pending': True,
                'task_id': str(task.id),
                'sentence': task.sentence,
                'target_word': task.target_word,
                'lang': task.lang,
                'task_type': task.task_type
            }, status=status.HTTP_200_OK)
        return Response({'has_pending': False}, status=status.HTTP_200_OK)


class WritingTaskDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, task_id):
        task = get_object_or_404(WritingTask, id=task_id, user=request.user)
        return Response({
            'task_id': str(task.id),
            'status': task.status,
            'sentence': task.sentence,
            'target_word': task.target_word,
            'lang': task.lang,
            'task_type': task.task_type,
            'result': task.result_data,
            'error': task.error_message
        }, status=status.HTTP_200_OK)
