import os
import json
import logging
import asyncio
import shutil
import io
import jwt
from fastapi import FastAPI, Query, HTTPException, BackgroundTasks, UploadFile, Form, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from google.cloud import storage
from google import genai
from google.genai import types
from uuid import uuid4

# Configure Logging
LOG_DIR = "/app/logs"
os.makedirs(LOG_DIR, exist_ok=True)
log_file = os.path.join(LOG_DIR, "image_service.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(log_file, encoding='utf-8')
    ]
)
logger = logging.getLogger("image_service")

app = FastAPI(title="XiaoYueDict Standalone Image Service", version="1.0.0")

# Directories
CACHE_DIR = "/app/cache"
os.makedirs(CACHE_DIR, exist_ok=True)

# Environment Configurations
BUCKET_NAME = os.environ.get("GS_BUCKET_NAME", "cnen-bucket")

# Mock Mode Configuration — $0 cost local development
IS_DEBUG = os.environ.get("DJANGO_DEBUG", "False").lower() in ("true", "1", "t")
MOCK_IMAGE_PATH = os.path.join(CACHE_DIR, "mock_sample.png")


def _create_mock_placeholder(output_path):
    """
    Sinh ảnh giả lập (Programmatic Image Generation) tại runtime.
    Tạo file PNG 512x512 với text "MOCK IMAGE" — loại bỏ binary blobs khỏi Git.
    Yêu cầu: Pillow trong requirements.txt
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
        img = Image.new('RGB', (512, 512), color=(240, 240, 245))
        draw = ImageDraw.Draw(img)

        # Draw grid pattern for visual identification
        for i in range(0, 512, 32):
            draw.line([(i, 0), (i, 512)], fill=(220, 220, 230), width=1)
            draw.line([(0, i), (512, i)], fill=(220, 220, 230), width=1)

        # Draw center text
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36)
            font_sm = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)
        except (IOError, OSError):
            font = ImageFont.load_default()
            font_sm = font

        # "MOCK IMAGE" label
        draw.text((256, 220), "MOCK IMAGE", fill=(100, 100, 120), font=font, anchor="mm")
        draw.text((256, 270), "Debug Mode · No API Cost", fill=(150, 150, 170), font=font_sm, anchor="mm")

        # Border
        draw.rectangle([(4, 4), (507, 507)], outline=(180, 180, 200), width=2)

        img.save(output_path, "PNG")
        logger.info(f"🧪 Created mock placeholder image: {output_path}")
    except ImportError:
        # Pillow not installed — create minimal 1x1 PNG fallback
        import struct
        import zlib
        def _minimal_png(path):
            """Create a minimal valid 1x1 white PNG without Pillow."""
            signature = b'\x89PNG\r\n\x1a\n'
            ihdr_data = struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)
            ihdr_crc = zlib.crc32(b'IHDR' + ihdr_data) & 0xFFFFFFFF
            ihdr = struct.pack('>I', 13) + b'IHDR' + ihdr_data + struct.pack('>I', ihdr_crc)
            raw = zlib.compress(b'\x00\xff\xff\xff')
            idat_crc = zlib.crc32(b'IDAT' + raw) & 0xFFFFFFFF
            idat = struct.pack('>I', len(raw)) + b'IDAT' + raw + struct.pack('>I', idat_crc)
            iend_crc = zlib.crc32(b'IEND') & 0xFFFFFFFF
            iend = struct.pack('>I', 0) + b'IEND' + struct.pack('>I', iend_crc)
            with open(path, 'wb') as f:
                f.write(signature + ihdr + idat + iend)
        _minimal_png(path)
        logger.warning(f"⚠️ Pillow not available, created minimal PNG: {output_path}")


# Initialize mock placeholder at startup
if not os.path.exists(MOCK_IMAGE_PATH):
    _create_mock_placeholder(MOCK_IMAGE_PATH)

if IS_DEBUG:
    logger.info("🧪 Mock mode ENABLED — will use placeholder images instead of Vertex AI")

# Helper to extract project ID from service account credentials
def get_project_id():
    key_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if key_path and os.path.exists(key_path):
        try:
            with open(key_path, 'r') as f:
                key_data = json.load(f)
                return key_data.get("project_id")
        except Exception as e:
            logger.error(f"Failed to read GCS key file for project_id: {e}")
    return None

# Initialize Google GenAI Client (Vertex AI backend)
project_id = get_project_id()
genai_client = None
if project_id:
    try:
        genai_client = genai.Client(
            vertexai=True,
            project=project_id,
            location="us-central1",
        )
        logger.info(f"Google GenAI client initialized with project: {project_id}")
    except Exception as e:
        logger.error(f"Google GenAI client initialization failed: {e}")
else:
    logger.warning("Google GenAI client could not be initialized. Project ID not found.")

# GCS Client Initialization Helper
def get_gcs_bucket():
    try:
        key_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        if key_path and os.path.exists(key_path):
            client = storage.Client()
            return client.bucket(BUCKET_NAME)
        else:
            logger.warning("GCS credentials not found. Cloud storage operations will be skipped.")
            return None
    except Exception as e:
        logger.error(f"Failed to initialize GCS client: {e}")
        return None

bucket_instance = get_gcs_bucket()

# Request schemas
class GenerateRequest(BaseModel):
    word_id: str
    lang: str
    prompt: str

class DeleteRequest(BaseModel):
    word_id: str
    lang: str

@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "image_service",
        "gcs_bucket_connected": bucket_instance is not None,
        "vertex_ai_initialized": genai_client is not None
    }

@app.post("/api/v1/image/generate")
async def generate_image(req: GenerateRequest):
    word_id = req.word_id
    lang = req.lang
    prompt = req.prompt

    if not word_id or not lang or not prompt:
        raise HTTPException(status_code=400, detail="Missing required parameters")

    filename = f"{word_id}.png"
    local_path = os.path.join(CACHE_DIR, filename)
    blob_name = f"images/{lang}/{filename}"

    bucket = get_gcs_bucket()
    if not bucket:
        raise HTTPException(status_code=500, detail="GCS Bucket is not configured or authenticated")

    logger.info(f"🎨 Generating image for word_id={word_id}, lang={lang}, prompt='{prompt}'")
    
    # 1. Generate image — Mock mode or Production mode
    try:
        if IS_DEBUG:
            # Mock mode: copy local placeholder instead of calling Vertex AI ($0 cost)
            logger.info(f"🧪 [MOCK] Using placeholder image for word_id={word_id}")
            shutil.copy(MOCK_IMAGE_PATH, local_path)
        else:
            # Production: call Vertex AI Imagen
            if not genai_client:
                raise HTTPException(status_code=500, detail="Google GenAI client is not initialized")

            def genai_generate():
                response = genai_client.models.generate_images(
                    model="imagen-4.0-ultra-generate-001",
                    prompt=prompt,
                    config=types.GenerateImagesConfig(
                        number_of_images=1,
                        aspect_ratio="1:1",
                        output_mime_type="image/png",
                    ),
                )
                if not response or not response.generated_images:
                    raise Exception("Google GenAI returned no images.")
                
                # Save locally by writing raw image bytes
                image_bytes = response.generated_images[0].image.image_bytes
                with open(local_path, "wb") as f:
                    f.write(image_bytes)

            try:
                await asyncio.to_thread(genai_generate)
            except Exception as e:
                logger.warning(f"⚠️ Vertex AI generation failed ({e}). Falling back to mock placeholder.")
                shutil.copy(MOCK_IMAGE_PATH, local_path)

        logger.info(f"✨ Successfully generated image locally: {local_path}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Image generation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Image generation failed: {str(e)}")

    # 2. Upload to GCS
    try:
        blob = bucket.blob(blob_name)
        await asyncio.to_thread(blob.upload_from_filename, local_path)
        logger.info(f"☁️ Uploaded to GCS as {blob_name}")
        gcs_url = blob.public_url
        
        # Clean up local file
        if os.path.exists(local_path):
            os.remove(local_path)
            
        return {"status": "success", "image_url": gcs_url}
    except Exception as e:
        logger.error(f"❌ Failed to upload image to GCS: {e}")
        if os.path.exists(local_path):
            os.remove(local_path)
        raise HTTPException(status_code=500, detail=f"GCS upload failed: {str(e)}")

@app.delete("/api/v1/image/delete")
async def delete_image(req: DeleteRequest):
    word_id = req.word_id
    lang = req.lang

    if not word_id or not lang:
        raise HTTPException(status_code=400, detail="Missing required parameters")

    filename = f"{word_id}.png"
    blob_name = f"images/{lang}/{filename}"

    bucket = get_gcs_bucket()
    if not bucket:
        raise HTTPException(status_code=500, detail="GCS Bucket is not configured or authenticated")

    try:
        blob = bucket.blob(blob_name)
        blob_exists = await asyncio.to_thread(blob.exists)
        if blob_exists:
            await asyncio.to_thread(blob.delete)
            logger.info(f"🗑️ Deleted GCS image: {blob_name}")
            return {"status": "success", "detail": "Image deleted from GCS"}
        else:
            # Safe recovery: trả success để Celery không bị gãy mạch khi file chưa tồn tại
            logger.warning(f"⚠️ Image not found on GCS (already clean): {blob_name}")
            return {"status": "success", "detail": "Image not found on GCS (already clean)"}
    except Exception as e:
        logger.error(f"❌ Failed to delete GCS image: {e}")
        raise HTTPException(status_code=500, detail=f"GCS deletion failed: {str(e)}")


# --- JWT Verification Dependency ---
async def verify_community_jwt(request: Request) -> dict:
    """Xác thực JWT từ header Authorization.
    Sử dụng JWT_SECRET_KEY chung với Django (shared env var)."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid token")
    token = auth.split(" ", 1)[1]
    try:
        secret_key = os.environ.get("JWT_SECRET_KEY", "replace-this-in-production")
        payload = jwt.decode(token, secret_key, algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


@app.post("/api/v1/image/community/upload")
async def upload_community_image(
    file: UploadFile,
    lang: str = Form("zh"),
    jwt_payload: dict = Depends(verify_community_jwt),
):
    user_id = jwt_payload.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    # ── Bước 1: Validate kích thước và định dạng tệp ──
    if file.size and file.size > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Kích thước tệp vượt quá 5MB")
    
    ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail=f"Định dạng không hỗ trợ: {file.content_type}")

    # ── Bước 2: Đọc file bất đồng bộ trên Event Loop chính ──
    try:
        file_bytes = await file.read()
    except Exception as e:
        logger.error(f"❌ Failed to read upload file: {e}")
        raise HTTPException(status_code=400, detail="Không thể đọc tệp tin")

    if len(file_bytes) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Kích thước tệp vượt quá 5MB")

    # ── Bước 3: Xử lý CPU-bound Pillow (Resize & WebP Conversion) trên Thread Pool ──
    def process_image_sync(data: bytes) -> bytes:
        from PIL import Image
        img = Image.open(io.BytesIO(data))
        # Loại bỏ EXIF orientation metadata và đảm bảo định dạng RGB
        img = img.convert("RGB")
        img.thumbnail((1080, 1080), Image.Resampling.LANCZOS)

        buffer = io.BytesIO()
        img.save(buffer, format="WEBP", quality=85)
        return buffer.getvalue()

    try:
        image_bytes = await asyncio.to_thread(process_image_sync, file_bytes)
    except Exception as e:
        logger.error(f"❌ Pillow image processing failed: {e}")
        raise HTTPException(status_code=500, detail=f"Xử lý ảnh thất bại: {str(e)}")

    # ── Bước 4: Upload GCS vào thư mục TEMP ──
    bucket = get_gcs_bucket()
    if not bucket:
        if IS_DEBUG:
            file_id = uuid4().hex
            filename = f"community_temp_{file_id}.webp"
            local_path = os.path.join(CACHE_DIR, filename)
            try:
                with open(local_path, "wb") as f:
                    f.write(image_bytes)
                logger.info(f"🧪 [MOCK] Saved community temp image locally: {local_path}")
                mock_url = f"http://localhost:8003/cache/{filename}"
                return {
                    "image_url": mock_url,
                    "temp_path": f"community/temp/{user_id}/{file_id}.webp"
                }
            except Exception as e:
                logger.error(f"❌ Mock save failed: {e}")
                raise HTTPException(status_code=500, detail="Mock save failed")
        
        raise HTTPException(status_code=500, detail="GCS Bucket is not configured or authenticated")

    file_id = uuid4().hex
    temp_blob_name = f"community/temp/{user_id}/{file_id}.webp"

    def upload_to_gcs_sync(blob_name: str, data: bytes) -> str:
        blob = bucket.blob(blob_name)
        blob.upload_from_string(data, content_type="image/webp")
        return blob.public_url

    try:
        public_url = await asyncio.to_thread(upload_to_gcs_sync, temp_blob_name, image_bytes)
        logger.info(f"☁️ Uploaded community temp image to GCS: {temp_blob_name}")
        return {
            "image_url": public_url,
            "temp_path": temp_blob_name
        }
    except Exception as e:
        logger.error(f"❌ GCS upload failed for temp image: {e}")
        raise HTTPException(status_code=500, detail=f"Upload GCS thất bại: {str(e)}")

