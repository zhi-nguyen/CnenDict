"""
AI Chat Service — FastAPI entry point.
Internal-only service that processes chat requests via Redis Pub/Sub.
All client-facing endpoints are handled by Django (authentication, authorization).
This service only exposes a health check and runs a Redis Pub/Sub listener.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from config import settings
from redis_client import RedisClient
from ai_agent import ChineseTutorAgent
from redis_listener import start_redis_listener

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ai_chat_service")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the Redis Pub/Sub listener on startup."""
    logger.info("🚀 Starting AI Chat Service (internal-only)...")

    listener_task = asyncio.create_task(start_redis_listener())
    logger.info("✅ Redis Pub/Sub listener task created.")

    yield

    logger.info("🛑 Shutting down AI Chat Service...")
    listener_task.cancel()
    try:
        await listener_task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="XiaoYue AI Chat Service (Internal)",
    description="Internal microservice for Chinese Tutoring Chat via Vertex AI Gemini. "
                "Not exposed to external clients — communicates via Redis Pub/Sub only.",
    version="2.0.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health_check():
    """Health check endpoint for Docker orchestration."""
    try:
        redis_client = RedisClient()
        client = await redis_client.get_client()
        redis_ok = await client.ping()
    except Exception as e:
        redis_ok = False
        logger.error(f"Health check failed to connect to Redis: {e}")

    try:
        agent = ChineseTutorAgent()
        gemini_ok = await agent.test_connection()
    except Exception as e:
        gemini_ok = False
        logger.error(f"Health check failed to verify Gemini connection: {e}")

    status_code = 200 if (redis_ok and gemini_ok) else 500

    return JSONResponse(
        status_code=status_code,
        content={
            "status": "healthy" if (redis_ok and gemini_ok) else "unhealthy",
            "redis_connected": redis_ok,
            "gemini_connected": gemini_ok,
            "service": "ai_chat_service",
            "mode": "internal_only",
        },
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8010, reload=True)
