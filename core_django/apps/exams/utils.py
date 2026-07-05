import os
import json
import uuid
from django.conf import settings
from django.db import transaction
from django.core.cache import cache
from django.core.files.storage import default_storage
from .models import Exam, Section, Paragraph, Question, Option
from .tasks import process_exam_media_task

def import_full_exam_data(exam_json_file, audio_file=None, image_mapping_file=None, images=None):
    """
    Parses and imports an entire HSK exam from JSON, audio, and image files.
    Returns a dictionary of results or raises an exception.
    """
    if not exam_json_file:
        raise ValueError('Missing exam_json file')

    try:
        exam_data = json.loads(exam_json_file.read().decode('utf-8'))
    except json.JSONDecodeError as e:
        raise ValueError(f'Invalid exam JSON: {e}')

    exam_id = exam_data.get('exam_metadata', {}).get('exam_id')
    if not exam_id:
        raise ValueError('Missing exam_id in exam_metadata')

    # Base directories for media
    audio_dir = f'exams/audio/{exam_id}'
    images_dir = f'exams/images/{exam_id}'

    # Save audio file
    audio_url = ''
    if audio_file:
        audio_path = os.path.join(audio_dir, audio_file.name)
        if default_storage.exists(audio_path):
            default_storage.delete(audio_path)
        saved_audio_path = default_storage.save(audio_path, audio_file)
        audio_url = settings.MEDIA_URL + saved_audio_path

    # Save images
    saved_images = {}
    if images:
        for img in images:
            img_path = os.path.join(images_dir, img.name)
            if default_storage.exists(img_path):
                default_storage.delete(img_path)
            saved_img_path = default_storage.save(img_path, img)
            saved_images[img.name] = settings.MEDIA_URL + saved_img_path

    # Parse image mapping
    image_mapping_by_desc = {}
    if image_mapping_file:
        try:
            mapping_data = json.loads(image_mapping_file.read().decode('utf-8'))
            for desc, val in mapping_data.items():
                filename = val.get('filename')
                if filename and filename in saved_images:
                    image_mapping_by_desc[desc.strip()] = saved_images[filename]
        except Exception as e:
            raise ValueError(f'Invalid image mapping JSON: {e}')

    # Process and Save Data to DB
    with transaction.atomic():
        metadata = exam_data.get('exam_metadata', {})
        settings_data = exam_data.get('exam_settings', {})
        
        exam, _ = Exam.objects.update_or_create(
            exam_id=exam_id,
            defaults={
                'exam_name': metadata.get('exam_name', ''),
                'exam_version': metadata.get('exam_version', '1.0'),
                'level': metadata.get('level', ''),
                'language': metadata.get('language', 'zh'),
                'total_questions': metadata.get('total_questions', 0),
                'total_time_minutes': metadata.get('total_time_minutes', 0),
                'total_score': metadata.get('total_score', 0),
                'passing_score': metadata.get('passing_score', 0),
                'allow_resume': settings_data.get('allow_resume', True),
                'max_attempts': settings_data.get('max_attempts', -1),
                'shuffle_questions': settings_data.get('shuffle_questions', False),
                'shuffle_options': settings_data.get('shuffle_options', False),
                'show_explanation_after': settings_data.get('show_explanation_after', 'exam_submitted'),
                'status': 1
            }
        )
        
        sections_data = exam_data.get('sections', [])
        for s_idx, sec_data in enumerate(sections_data):
            section_name = sec_data.get('section_name', '')
            s_audio_url = audio_url if section_name == 'Listening' else sec_data.get('section_audio_url', '')
            
            section, _ = Section.objects.update_or_create(
                exam=exam,
                section_id=sec_data.get('section_id'),
                defaults={
                    'section_name': section_name,
                    'part_number': sec_data.get('part_number', 0),
                    'instruction': sec_data.get('instruction', ''),
                    'section_audio_url': s_audio_url,
                    'ordering': s_idx
                }
            )
            
            section.paragraphs.all().delete()

            passages_dict = {}
            paragraph_counter = 1
            questions_list = sec_data.get('questions', [])

            for q_idx, q_data in enumerate(questions_list):
                q_id = q_data.get('question_id')
                q_desc = q_data.get('image_description', '').strip()
                q_image_url = q_data.get('image_url', '')
                # Ưu tiên lấy ảnh mới tải lên nếu khớp mô tả
                if q_desc in image_mapping_by_desc:
                    q_image_url = image_mapping_by_desc[q_desc]
                            
                q_audio_raw = q_data.get('audio_url', '')
                q_audio_clean = '' if (q_audio_raw.startswith('audio/') or 'q_listen_' in q_audio_raw) else q_audio_raw

                q_passage = q_data.get('paragraph', '').strip()
                q_prompt = q_data.get('question_text', '').strip()

                paragraph_obj = None
                if q_passage:
                    if q_passage not in passages_dict:
                        p_id = f"para_{section.section_id}_{paragraph_counter}"
                        lines = [line.strip() for line in q_passage.split('\n') if line.strip()]
                        title = f"Đoạn văn {paragraph_counter}"
                        for line in lines:
                            if len(line) > 5 and not any(k in line for k in ["阅读", "回答问题", "Read", "Passage"]):
                                title = line[:50]
                                if len(line) > 50:
                                    title += "..."
                                break
                        
                        paragraph_obj = Paragraph.objects.create(
                            section=section,
                            paragraph_id=p_id,
                            title=title,
                            content=q_passage,
                            ordering=paragraph_counter
                        )
                        passages_dict[q_passage] = paragraph_obj
                        paragraph_counter += 1
                    else:
                        paragraph_obj = passages_dict[q_passage]

                question, _ = Question.objects.update_or_create(
                    section=section,
                    question_id=q_id,
                    defaults={
                        'question_type': q_data.get('question_type', 'multiple_choice'),
                        'difficulty': q_data.get('difficulty', 'easy'),
                        'points': q_data.get('points', 5),
                        'tags': q_data.get('tags', []),
                        'audio_url': q_audio_clean,
                        'audio_start_time': q_data.get('audio_start_time', ''),
                        'audio_end_time': q_data.get('audio_end_time', ''),
                        'audio_script': q_data.get('audio_script', ''),
                        'question_text': q_prompt,
                        'image_url': q_image_url,
                        'image_description': q_data.get('image_description', ''),
                        'correct_answer': q_data.get('correct_answer', ''),
                        'explanation': q_data.get('explanation', ''),
                        'paragraph': paragraph_obj,
                        'ordering': q_idx
                    }
                )
                
                for o_idx, o_data in enumerate(q_data.get('options', [])):
                    o_id = o_data.get('option_id')
                    o_image_url = o_data.get('image_url', '')
                    
                    o_desc = o_data.get('image_description', '').strip()
                    # Ưu tiên lấy ảnh mới tải lên nếu khớp mô tả
                    if o_desc in image_mapping_by_desc:
                        o_image_url = image_mapping_by_desc[o_desc]
                                
                    Option.objects.update_or_create(
                        question=question,
                        option_id=o_id,
                        defaults={
                            'text': o_data.get('text', ''),
                            'image_url': o_image_url,
                            'image_description': o_data.get('image_description', ''),
                            'ordering': o_idx
                        }
                    )

    # Evict cache for this exam and list caches
    clear_exam_cache(exam_id)

    # Trigger background task to process and upload to GCS on commit
    transaction.on_commit(lambda: process_exam_media_task.delay(exam_id))

    return {
        'exam_id': exam_id,
        'audio_url': audio_url,
        'images_uploaded': len(saved_images)
    }


def import_exam_from_zip(zip_file):
    """
    Imports an HSK exam directly from an uploaded zip file containing:
    - test/*.json
    - audio/*.mp3
    - img_mapping/*.json
    - img/*.(png|jpg|jpeg)
    """
    import zipfile
    from django.core.files.base import ContentFile

    if not zip_file:
        raise ValueError('Missing ZIP file')

    # Mở file ZIP trong bộ nhớ
    try:
        zip_ref = zipfile.ZipFile(zip_file)
    except zipfile.BadZipFile as e:
        raise ValueError(f'Invalid ZIP file: {e}')

    with zip_ref:
        namelist = zip_ref.namelist()

        # Xác định xem cấu trúc ZIP có thư mục bọc ngoài không (VD: HSK1_NEW_UUID_001/test/ thay vì test/)
        # Ta quét tìm vị trí của "test/" để tính toán prefix
        prefix = ""
        for path in namelist:
            if "test/" in path:
                idx = path.find("test/")
                prefix = path[:idx]
                break

        # Khởi tạo đường dẫn các file cần tìm
        json_path = None
        audio_path = None
        mapping_path = None
        image_paths = []

        for path in namelist:
            # Loại bỏ prefix để chuẩn hóa
            norm_path = path[len(prefix):] if path.startswith(prefix) else path

            # Bỏ qua nếu là thư mục
            if path.endswith('/'):
                continue

            if norm_path.startswith("test/") and norm_path.endswith(".json"):
                json_path = path
            elif norm_path.startswith("audio/") and norm_path.endswith(".mp3"):
                # Ưu tiên lấy hsk_listening_exam.mp3 làm audio chính
                if not audio_path or "hsk_listening_exam.mp3" in norm_path:
                    audio_path = path
            elif norm_path.startswith("img_mapping/") and norm_path.endswith(".json"):
                mapping_path = path
            elif norm_path.startswith("img/") and not path.endswith('.txt'): # Bỏ qua file txt báo lỗi rỗng
                image_paths.append(path)

        if not json_path:
            raise ValueError("Không tìm thấy file JSON đề thi trong thư mục 'test/' của file ZIP.")

        # 1. Đọc file JSON đề thi
        try:
            json_data = zip_ref.read(json_path)
            exam_json_file = ContentFile(json_data, name=os.path.basename(json_path))
        except Exception as e:
            raise ValueError(f"Không thể đọc file JSON đề thi từ ZIP: {e}")

        # 2. Đọc file Audio (nếu có)
        audio_file = None
        if audio_path:
            try:
                audio_data = zip_ref.read(audio_path)
                audio_file = ContentFile(audio_data, name=os.path.basename(audio_path))
            except Exception as e:
                raise ValueError(f"Không thể đọc file Audio từ ZIP: {e}")

        # 3. Đọc file Mapping (nếu có)
        image_mapping_file = None
        if mapping_path:
            try:
                mapping_data = zip_ref.read(mapping_path)
                image_mapping_file = ContentFile(mapping_data, name=os.path.basename(mapping_path))
            except Exception as e:
                raise ValueError(f"Không thể đọc file Image Mapping từ ZIP: {e}")

        # 4. Đọc các file ảnh minh họa
        images = []
        for img_path in image_paths:
            try:
                img_data = zip_ref.read(img_path)
                img_file = ContentFile(img_data, name=os.path.basename(img_path))
                images.append(img_file)
            except Exception as e:
                raise ValueError(f"Không thể đọc file ảnh {img_path} từ ZIP: {e}")

    # 5. Gọi hàm import_full_exam_data để lưu database
    return import_full_exam_data(
        exam_json_file=exam_json_file,
        audio_file=audio_file,
        image_mapping_file=image_mapping_file,
        images=images
    )


def clear_exam_cache(exam_id):
    """Xóa cache của đề thi và danh sách đề thi để đồng bộ frontend."""
    from django.core.cache import cache
    cache.delete(f"exam:data:{exam_id}")
    
    # Lấy real cache backend để tương thích cả django-redis và Django built-in RedisCache
    real_cache = cache._connections['default'] if hasattr(cache, '_connections') else cache
    redis_client = None
    if hasattr(real_cache, 'client'):
        try:
            redis_client = real_cache.client.get_client()
        except Exception:
            pass
    elif hasattr(real_cache, '_cache') and hasattr(real_cache._cache, 'get_client'):
        try:
            redis_client = real_cache._cache.get_client()
        except Exception:
            pass

    if redis_client:
        try:
            # Xóa các key cache danh sách đề thi (hỗ trợ cả các pattern của redis)
            keys = redis_client.keys("*exams:list:*")
            if keys:
                redis_client.delete(*keys)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Failed to clear exam list cache: {e}")
