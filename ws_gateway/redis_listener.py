"""
Redis Pub/Sub Listener — subscribes to:
  1. 'ws:notifications' channel — JSON text messages forwarded to WebSocket clients
  2. 'ws:audio:*' pattern — binary audio chunks forwarded as raw bytes

Runs as background asyncio tasks during the FastAPI lifespan.
"""

import os
import json
import asyncio
import logging
import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
TEXT_CHANNEL = "ws:notifications"
AUDIO_CHANNEL_PATTERN = "ws:audio:*"


async def _listen_text(pubsub, manager):
    """
    Listen for JSON text messages on 'ws:notifications' and forward to WebSocket clients.

    Expected message format:
    {
        "user_id": "123",
        "type": "score_complete" | "ai_chat_chunk" | "ai_chat_complete" | ...,
        "payload": { ... }
    }
    """
    async for raw_message in pubsub.listen():
        if raw_message["type"] != "message":
            continue

        try:
            data = json.loads(raw_message["data"])
            user_id = data.get("user_id")
            if not user_id:
                logger.warning(f"Message missing user_id: {data}")
                continue

            # Forward to all WebSocket connections of this user
            await manager.send_personal_message(data, str(user_id))

        except json.JSONDecodeError:
            logger.warning(f"Invalid JSON from Redis: {raw_message['data']}")
        except Exception as e:
            logger.error(f"Error forwarding text message: {e}")


async def _listen_binary(pubsub, manager):
    """
    Listen for binary audio chunks on 'ws:audio:{user_id}' channels
    and forward raw bytes to WebSocket clients.

    Channel format: ws:audio:{user_id}
    Data: raw MP3 binary bytes (NOT decoded as text)
    """
    async for raw_message in pubsub.listen():
        if raw_message["type"] != "pmessage":
            continue

        try:
            # Extract user_id from channel name: b"ws:audio:{user_id}"
            channel = raw_message["channel"]
            if isinstance(channel, bytes):
                channel = channel.decode("utf-8")

            # Parse user_id from "ws:audio:{user_id}"
            parts = channel.split(":", 2)
            if len(parts) != 3:
                logger.warning(f"Unexpected audio channel format: {channel}")
                continue

            user_id = parts[2]
            audio_data = raw_message["data"]

            # Forward raw binary audio to WebSocket client
            await manager.send_binary_message(audio_data, user_id)

        except Exception as e:
            logger.error(f"Error forwarding binary audio: {e}")


async def redis_listener(manager):
    """
    Subscribe to both text and binary Redis channels and forward to WebSocket clients.
    Runs both listeners concurrently using asyncio.gather.
    """
    while True:
        try:
            # Text client — for JSON messages (decode_responses=True)
            text_redis = aioredis.from_url(
                REDIS_URL,
                decode_responses=True,
                socket_timeout=None,
                socket_keepalive=True,
            )
            text_pubsub = text_redis.pubsub()
            await text_pubsub.subscribe(TEXT_CHANNEL)
            logger.info(f"Subscribed to Redis text channel: {TEXT_CHANNEL}")

            # Binary client — for audio data (decode_responses=False to keep raw bytes)
            binary_redis = aioredis.from_url(
                REDIS_URL,
                decode_responses=False,
                socket_timeout=None,
                socket_keepalive=True,
            )
            binary_pubsub = binary_redis.pubsub()
            await binary_pubsub.psubscribe(AUDIO_CHANNEL_PATTERN)
            logger.info(f"Subscribed to Redis binary channel pattern: {AUDIO_CHANNEL_PATTERN}")

            # Run both listeners concurrently
            await asyncio.gather(
                _listen_text(text_pubsub, manager),
                _listen_binary(binary_pubsub, manager),
            )

        except Exception as e:
            logger.error(f"Redis connection error: {e}. Reconnecting in 3s...")
            await asyncio.sleep(3)
