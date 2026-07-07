import logging
import requests
from django.core.cache import cache
from celery import shared_task
from apps.dictionary_zh.models import ZhWord
from apps.dictionary_en.models import EnWord
from core_project.ws_utils import ws_notify

logger = logging.getLogger(__name__)

IMAGE_SERVICE_URL = "http://image-service:8003/api/v1/image/generate"
IMAGE_DELETE_URL = "http://image-service:8003/api/v1/image/delete"

def get_word_by_id(word_id, lang):
    try:
        if lang == 'zh':
            return ZhWord.objects.get(pk=word_id)
        else:
            return EnWord.objects.get(pk=word_id)
    except (ZhWord.DoesNotExist, EnWord.DoesNotExist):
        return None


def _resolve_image_prompt(word_id, lang, word):
    """
    Builds image prompt for AI generation:
    - Uses the first available dictionary example sentence (in Vietnamese / translation if available, or original)
    - Fallback: Uses the vocabulary word itself if no example exists
    - Implements strict realistic photography or 3D real-world rendering style to represent the concept visually without diagrams, text, labels, or typography.
    """
    # 1. Fetch concept sentence description (prefer example)
    concept_description = ""
    try:
        # Retrieve the first example related to the word
        first_example = word.examples.first() if hasattr(word, 'examples') else None
        if first_example:
            # Prefer vietnamese translation for better description if available, otherwise original sentence
            concept_description = getattr(first_example, 'vietnamese', '') or getattr(first_example, 'english', '') or getattr(first_example, 'chinese', '')
            concept_description = concept_description.strip()
    except Exception as e:
        logger.warning(f"Error fetching examples for word_id={word_id}: {e}")

    # Fallback to word text itself if no example found
    if not concept_description:
        concept_description = word.word if hasattr(word, 'word') else str(word)

    # 2. Strict Style Base (Realistic / 3D Photography, banning diagrams, text, letters, icons, sketches)
    style_base = (
        "High-quality commercial photography, realistic 3D real-world rendering, detailed texture, depth of field, "
        "studio lighting. Solid realistic representation of the object or scene. "
        "Strictly NO text, NO words, NO letters, NO labels, NO typography, NO symbols, NO characters. "
        "Strictly NO diagrams, NO schematics, NO flat vectors, NO illustrations, NO sketches, NO infographics."
    )

    prompt = (
        f"{style_base} "
        f"A beautiful real-world photograph or 3D realistic rendering representing the following concept: '{concept_description}'. "
        f"Focus entirely on depicting the realistic subject, object, or action. Clean backdrop, zero text on screen."
    )
    return prompt


@shared_task
def generate_word_image_task(word_id, lang, user_id, **kwargs):
    logger.info(f"Celery task: image generation is disabled. word_id={word_id}, lang={lang}")
    redis_key = f"img:{lang}:{word_id}"
    cache.set(redis_key, {"status": "collecting"}, timeout=300)
    
    # Notify client via WebSocket about the collecting state
    ws_notify(
        user_id=user_id,
        event_type="image_complete",
        title="Đang thu thập hình ảnh",
        payload={"word_id": word_id, "image_url": None, "status": "collecting"},
        persist=False,
    )

@shared_task
def trigger_image_regeneration_task(word_id, lang, user_id, **kwargs):
    logger.info(f"Celery task: regenerating image for word_id={word_id}, lang={lang}, user={user_id}")
    word = get_word_by_id(word_id, lang)
    if not word:
        return

    # Delete existing GCS file via image-service
    try:
        res = requests.delete(IMAGE_DELETE_URL, json={
            "word_id": str(word_id),
            "lang": lang
        }, timeout=10)
        logger.info(f"Deleted old image from GCS: {res.status_code}")
    except Exception as e:
        logger.error(f"Failed to delete GCS image: {e}")

    # Reset DB image_url
    word.image_url = ''
    word.save()

    # Re-run generation
    generate_word_image_task(word_id, lang, user_id)
