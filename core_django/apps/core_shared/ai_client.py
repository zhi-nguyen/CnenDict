"""
Module-level Singleton cho Google Vertex AI (genai) Client.

Khởi tạo 1 lần duy nhất khi module được import lần đầu,
tái sử dụng xuyên suốt mọi Celery task trong hệ thống.

⚠️  USAGE CONTRACT:
    Module này KHÔNG nên được import từ Django views hoặc serializers.
    Chỉ sử dụng bên trong Celery tasks hoặc management commands.

Usage:
    from apps.core_shared.ai_client import get_genai_client

    client = get_genai_client()
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=text,
        config={'system_instruction': prompt}
    )
"""

import os
import logging

logger = logging.getLogger(__name__)

_genai_client = None


def get_genai_client():
    """
    Lazy-initialized singleton cho Google Vertex AI genai Client.

    Sử dụng Priority PayGo routing header để tối ưu latency và chi phí.
    Client được khởi tạo 1 lần duy nhất, tái sử dụng cho mọi request sau đó.

    Returns:
        genai.Client: Singleton instance đã được cấu hình cho Vertex AI.

    Raises:
        ImportError: Nếu thư viện google-genai chưa được cài đặt.
        Exception: Nếu khởi tạo client thất bại (thiếu credentials, v.v.).
    """
    global _genai_client
    if _genai_client is None:
        try:
            from google import genai

            project = os.environ.get("GOOGLE_CLOUD_PROJECT", "project-99192cc3-792c-4507-b70")
            location = os.environ.get("GOOGLE_CLOUD_LOCATION", "asia-southeast1")

            _genai_client = genai.Client(
                vertexai=True,
                project=project,
                location=location,
                http_options={
                    'headers': {
                        'X-Vertex-AI-LLM-Shared-Request-Type': 'priority'
                    }
                }
            )
            logger.info(f"✅ Vertex AI genai Client initialized: project={project}, location={location}")
        except Exception as e:
            logger.error(f"❌ Failed to initialize Vertex AI genai Client: {e}")
            raise

    return _genai_client
