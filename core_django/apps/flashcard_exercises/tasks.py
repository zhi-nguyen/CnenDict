import json
import re
import hashlib
import logging
import requests
from django.core.cache import cache
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from celery import shared_task
from celery.exceptions import Retry
from core_project.ws_utils import ws_notify

from .models import FlashcardExercise, UserFlashcardHistory, WritingTask
from .prompts import (
    get_exercise_system_prompt,
    get_writing_check_system_prompt,
    get_exercise_prompt,
    get_writing_prompt,
)

logger = logging.getLogger(__name__)


def handle_task_failure(writing_task_id, user_id, lang, cost, error_msg):
    from apps.gamification.coin_service import CoinService
    from django.contrib.auth import get_user_model
    
    if writing_task_id:
        try:
            task_obj = WritingTask.objects.get(id=writing_task_id)
            task_obj.status = 'FAILED'
            task_obj.error_message = error_msg
            task_obj.save()
        except WritingTask.DoesNotExist:
            pass

    if cost > 0 and user_id:
        User = get_user_model()
        try:
            user = User.objects.get(id=user_id)
            CoinService.refund_coins(
                user=user,
                lang=lang,
                amount=cost,
                reference_id=str(writing_task_id) if writing_task_id else '',
                note=f"Refund for writing task failure"
            )
        except Exception as ex:
            logger.error(f"Failed to refund coins for user {user_id}: {ex}")


def clean_json_string(raw_text):
    """Strip markdown code block wrappers if any."""
    text = raw_text.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def call_tts_service(text, lang):
    """Gọi internal tts-service và lưu vào Django Storage."""
    voice = 'zh-CN-XiaoxiaoNeural' if lang == 'zh' else 'en-US-AriaNeural'
    try:
        tts_internal_url = f"http://tts-service:8002/api/v1/tts?text={requests.utils.quote(text)}&lang={lang}&voice={voice}"
        logger.info(f"Calling internal TTS service: {tts_internal_url}")
        response = requests.get(tts_internal_url, timeout=15)
        response.raise_for_status()

        # Save to default storage
        text_hash = hashlib.md5(f"{text}:{voice}".encode('utf-8')).hexdigest()
        filename = f"flashcard_audio/{text_hash}.mp3"

        # Check if file already exists in storage
        if default_storage.exists(filename):
            return default_storage.url(filename)

        saved_path = default_storage.save(filename, ContentFile(response.content))
        return default_storage.url(saved_path)
    except Exception as e:
        logger.error(f"Failed to generate TTS audio: {e}")
        return ""


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def generate_exercises_task(self, word, lang, user_id=None, **kwargs):
    logger.info(f"Starting exercise generation task for: {word} ({lang})")
    
    # 1. Fetch all existing exercises from DB
    exercises = FlashcardExercise.objects.filter(word=word, lang=lang)
    
    # If user_id is provided, try to find unused exercises
    if user_id:
        completed_ids = list(UserFlashcardHistory.objects.filter(
            user_id=user_id, word=word, lang=lang
        ).values_list('exercise_id', flat=True))
        
        unused_reading = [ex for ex in exercises if ex.exercise_type == 'reading' and ex.id not in completed_ids]
        unused_listening = [ex for ex in exercises if ex.exercise_type == 'listening' and ex.id not in completed_ids]
        
        # If both types have unused exercises, return them!
        if unused_reading and unused_listening:
            logger.info("Found unused exercises in DB cache for user.")
            reading_ex = unused_reading[0]
            listening_ex = unused_listening[0]
            
            result_data = {
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
            ws_notify(
                user_id=user_id,
                event_type='flashcard_exercises_ready',
                title='Bài tập đã sẵn sàng',
                payload={'status': 'SUCCESS', 'word': word, 'lang': lang, 'exercises': result_data},
                persist=False
            )
            return result_data

        # If they've reached the 10 limit for either type, clear history for rotation
        reading_history_count = UserFlashcardHistory.objects.filter(
            user_id=user_id, word=word, lang=lang, exercise_type='reading'
        ).count()
        listening_history_count = UserFlashcardHistory.objects.filter(
            user_id=user_id, word=word, lang=lang, exercise_type='listening'
        ).count()
        
        if reading_history_count >= 10 or listening_history_count >= 10:
            logger.info(f"User reached 10 exercises limit for word: {word}. Resetting history.")
            UserFlashcardHistory.objects.filter(user_id=user_id, word=word, lang=lang).delete()
            # Select first available exercises to start rotation
            reading_ex = exercises.filter(exercise_type='reading').first()
            listening_ex = exercises.filter(exercise_type='listening').first()
            if reading_ex and listening_ex:
                result_data = {
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
                ws_notify(
                    user_id=user_id,
                    event_type='flashcard_exercises_ready',
                    title='Bài tập đã sẵn sàng',
                    payload={'status': 'SUCCESS', 'word': word, 'lang': lang, 'exercises': result_data},
                    persist=False
                )
                return result_data

    # 2. Call AI via Vertex AI to generate a new pair of exercises
    try:
        from apps.core_shared.ai_client import get_genai_client
        from google.genai import errors

        client = get_genai_client()
        
        # Build exclusion lists
        exclude_reading = [ex.content.get('question') for ex in exercises if ex.exercise_type == 'reading']
        exclude_listening = [ex.content.get('sentence') for ex in exercises if ex.exercise_type == 'listening']
        
        prompt = get_exercise_prompt(word, lang, exclude_reading=exclude_reading, exclude_listening=exclude_listening)
        
        logger.info(f"Sending prompt to Gemini: {prompt}")
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config={
                'system_instruction': get_exercise_system_prompt(lang),
                'response_mime_type': 'application/json'
            }
        )

        raw_text = response.text
        cleaned_text = clean_json_string(raw_text)
        logger.info(f"Received raw AI output: {cleaned_text}")
        
        parsed = json.loads(cleaned_text)
        
        # Save exercises to DB
        created_exercises = {}
        for ex_type in ['reading', 'listening']:
            if ex_type in parsed:
                content = parsed[ex_type]
                audio_url = ""
                if ex_type == 'listening':
                    sentence = content.get('sentence', '')
                    if sentence:
                        audio_url = call_tts_service(sentence, lang)

                exercise = FlashcardExercise.objects.create(
                    word=word,
                    lang=lang,
                    exercise_type=ex_type,
                    content=content,
                    audio_url=audio_url
                )

                created_exercises[ex_type] = {
                    'id': str(exercise.id),
                    'content': content,
                    'audio_url': audio_url
                }

        # Clear Redis processing flag
        cache_key = f"flashcard_ex:{word}:{lang}"
        cache.delete(cache_key)

        if user_id:
            ws_notify(
                user_id=user_id,
                event_type='flashcard_exercises_ready',
                title='Bài tập đã sẵn sàng',
                payload={'status': 'SUCCESS', 'word': word, 'lang': lang, 'exercises': created_exercises},
                persist=False
            )
        
        return created_exercises

    except errors.APIError as e:
        if e.code == 429 or "429" in str(e) or "ResourceExhausted" in str(e):
            raise self.retry(exc=e)
        raise e
    except Exception as e:
        logger.error(f"Error in generate_exercises_task: {e}")
        if user_id:
            ws_notify(
                user_id=user_id,
                event_type='flashcard_exercises_failed',
                title='Không thể tạo bài tập',
                payload={'status': 'FAILED', 'word': word, 'lang': lang, 'error': str(e)},
                persist=False
            )
        raise e


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def check_writing_task(self, sentence, target_word, lang, user_id=None, cost=0, writing_task_id=None, **kwargs):
    logger.info(f"Starting writing grammar check task for word: {target_word}, task_id: {writing_task_id}")
    
    try:
        from apps.core_shared.ai_client import get_genai_client
        from google.genai import errors

        client = get_genai_client()
        prompt = get_writing_prompt(sentence, target_word, lang)
        
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config={
                'system_instruction': get_writing_check_system_prompt(lang),
                'response_mime_type': 'application/json'
            }
        )

        raw_text = response.text
        cleaned_text = clean_json_string(raw_text)
        logger.info(f"Writing check result: {cleaned_text}")
        
        result_data = json.loads(cleaned_text)

        if writing_task_id:
            try:
                task_obj = WritingTask.objects.get(id=writing_task_id)
                task_obj.status = 'SUCCESS'
                task_obj.result_data = result_data
                task_obj.save()
            except WritingTask.DoesNotExist:
                pass

        if user_id:
            ws_notify(
                user_id=user_id,
                event_type='writing_check_complete',
                title='Đã kiểm tra ngữ pháp',
                payload={
                    'status': 'SUCCESS',
                    'result': result_data,
                    'sentence': sentence,
                    'target_word': target_word,
                    'task_id': str(writing_task_id) if writing_task_id else ''
                },
                persist=False
            )
        return result_data

    except errors.APIError as e:
        if e.code == 429 or "429" in str(e) or "ResourceExhausted" in str(e):
            raise self.retry(exc=e)
        handle_task_failure(writing_task_id, user_id, lang, cost, str(e))
        if user_id:
            ws_notify(
                user_id=user_id,
                event_type='writing_check_failed',
                title='Lỗi kiểm tra câu',
                payload={'status': 'FAILED', 'error': str(e), 'task_id': str(writing_task_id) if writing_task_id else ''},
                persist=False
            )
        raise e
    except Exception as e:
        logger.error(f"Error in check_writing_task: {e}")
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e)
            
        handle_task_failure(writing_task_id, user_id, lang, cost, str(e))
        if user_id:
            ws_notify(
                user_id=user_id,
                event_type='writing_check_failed',
                title='Lỗi kiểm tra câu',
                payload={'status': 'FAILED', 'error': str(e), 'task_id': str(writing_task_id) if writing_task_id else ''},
                persist=False
            )
        raise e


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def check_general_writing_task(self, sentence, lang, user_id=None, cost=0, writing_task_id=None, **kwargs):
    logger.info(f"Starting general writing check task for user: {user_id}, task_id: {writing_task_id}")
    
    try:
        from apps.core_shared.ai_client import get_genai_client
        from google.genai import errors

        client = get_genai_client()
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
        cleaned_text = clean_json_string(raw_text)
        logger.info(f"General writing check result: {cleaned_text}")
        
        result_data = json.loads(cleaned_text)

        if writing_task_id:
            try:
                task_obj = WritingTask.objects.get(id=writing_task_id)
                task_obj.status = 'SUCCESS'
                task_obj.result_data = result_data
                task_obj.save()
            except WritingTask.DoesNotExist:
                pass

        if user_id:
            ws_notify(
                user_id=user_id,
                event_type='general_writing_check_complete',
                title='Đã chấm điểm bài viết',
                payload={
                    'status': 'SUCCESS',
                    'result': result_data,
                    'sentence': sentence,
                    'task_id': str(writing_task_id) if writing_task_id else ''
                },
                persist=False
            )
        return result_data

    except errors.APIError as e:
        if e.code == 429 or "429" in str(e) or "ResourceExhausted" in str(e):
            raise self.retry(exc=e)
        handle_task_failure(writing_task_id, user_id, lang, cost, str(e))
        if user_id:
            ws_notify(
                user_id=user_id,
                event_type='general_writing_check_failed',
                title='Lỗi chấm điểm bài viết',
                payload={'status': 'FAILED', 'error': str(e), 'task_id': str(writing_task_id) if writing_task_id else ''},
                persist=False
            )
        raise e
    except Exception as e:
        logger.error(f"Error in check_general_writing_task: {e}")
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e)
            
        handle_task_failure(writing_task_id, user_id, lang, cost, str(e))
        if user_id:
            ws_notify(
                user_id=user_id,
                event_type='general_writing_check_failed',
                title='Lỗi chấm điểm bài viết',
                payload={'status': 'FAILED', 'error': str(e), 'task_id': str(writing_task_id) if writing_task_id else ''},
                persist=False
            )
        raise e
