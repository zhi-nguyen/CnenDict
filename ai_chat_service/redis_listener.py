"""
Redis Pub/Sub Listener for AI Chat Service.
Listens to 'ai:chat:request:*' channels, calls Gemini via Vertex AI,
synthesizes speech in real-time using Azure Speech Service, and publishes results back via Redis:
  - Text/JSON responses → 'ws:notifications' channel
  - Binary audio chunks → 'ws:audio:{user_id}' per-user channel
"""

import json
import logging
import asyncio
import uuid
import re
from typing import Any, Dict

import azure.cognitiveservices.speech as speechsdk
from google.genai import types

from config import settings
from redis_client import RedisClient
from ai_agent import ChineseTutorAgent
from role_mapper import ROLE_RELATIONSHIPS
from tts_handler import get_voice_presets, _sanitize_text_for_audio
from parser import StreamTutorParser

logger = logging.getLogger(__name__)

# Initialize Azure Speech Config
try:
    speech_config = speechsdk.SpeechConfig(
        subscription=settings.AZURE_SPEECH_KEY,
        region=settings.AZURE_SPEECH_REGION,
    )
    speech_config.set_speech_synthesis_output_format(
        speechsdk.SpeechSynthesisOutputFormat.Audio24Khz160KBitRateMonoMp3
    )
    logger.info(f"✅ Azure Speech Service initialized with region: {settings.AZURE_SPEECH_REGION}")
except Exception as e:
    logger.error(f"❌ Failed to initialize Azure Speech Service: {e}")
    speech_config = None


async def _publish_json(client, user_id: str, msg_type: str, payload: dict):
    """Helper to publish a JSON message to ws:notifications."""
    message = {
        "id": str(uuid.uuid4()),
        "user_id": str(user_id),
        "type": msg_type,
        "payload": payload,
    }
    await client.publish("ws:notifications", json.dumps(message, ensure_ascii=False))


async def _dispatch_celery_task(client, task_name: str, task_args: list, task_kwargs: dict = None, queue_name: str = "queue_chat"):
    """Helper to dispatch a Celery task to Redis queue."""
    import base64
    if task_kwargs is None:
        task_kwargs = {}
    
    body_data = [task_args, task_kwargs, {"callbacks": None, "errbacks": None, "chain": None, "chord": None}]
    body_str = json.dumps(body_data)
    body_b64 = base64.b64encode(body_str.encode('utf-8')).decode('utf-8')
    
    celery_id = str(uuid.uuid4())
    celery_payload = {
        "headers": {
            "lang": "py",
            "task": task_name,
            "id": celery_id,
            "root_id": celery_id,
            "parent_id": None,
            "group": None,
            "meth": None,
            "shadow": None,
            "eta": None,
            "expires": None,
            "retries": 0,
            "timelimit": [None, None],
            "argsrepr": repr(task_args),
            "kwargsrepr": repr(task_kwargs),
            "origin": "ai_chat_service"
        },
        "properties": {
            "correlation_id": celery_id,
            "reply_to": "",
            "delivery_mode": 2,
            "delivery_info": {
                "exchange": "",
                "routing_key": queue_name
            },
            "priority": 0,
            "body_encoding": "base64",
            "delivery_tag": celery_id
        },
        "content-encoding": "utf-8",
        "content-type": "application/json",
        "body": body_b64
    }
    await client.rpush(queue_name, json.dumps(celery_payload))
    logger.info(f"Dispatched Celery task {task_name} to queue {queue_name}")


async def process_chat_request(redis_client: RedisClient, agent: ChineseTutorAgent, payload: Dict[str, Any]):
    """
    Process a single chat request:
    1. Retrieve conversation history
    2. Determine roles & sulking level
    3. Stream response from Gemini
    4. Synthesize text to speech on-the-fly via Azure Speech Service and publish:
       - Text chunks via ws:notifications (JSON)
       - Binary audio via ws:audio:{user_id} (raw bytes)
    5. Save final response and notify completion
    """
    user_id = payload.get("user_id")
    user_text = payload.get("user_text")
    persona_id = payload.get("persona_id")
    if not user_id or not user_text:
        logger.warning(f"Invalid chat request payload: {payload}")
        return

    # Retrieve dynamic persona and emotional state parameters from payload
    agent_name = payload.get("agent_name", "小月")
    personality_desc = payload.get("personality_desc", "Vui vẻ")
    user_honorific = payload.get("user_honorific", "师兄")
    agent_self_ref = payload.get("agent_self_ref", "妹妹")
    
    joy_current = float(payload.get("joy_current", 0.5))
    sad_current = float(payload.get("sad_current", 0.1))
    joy_sensitivity = float(payload.get("joy_sensitivity", 1.0))
    sad_sensitivity = float(payload.get("sad_sensitivity", 0.5))
    joy_decay_rate = float(payload.get("joy_decay_rate", 0.4))
    sad_decay_rate = float(payload.get("sad_decay_rate", 0.6))
    
    learning_language = payload.get("learning_language", "zh")
    context_setting = payload.get("context_setting", "wuxia")
    user_level = payload.get("user_level", "Beginner")
    user_name = payload.get("user_name", "User")
    relation_type = payload.get("relation_type", "default")

    # Derive language-aware xưng hô variables
    user_honorific_vi = user_honorific
    agent_self_ref_vi = agent_self_ref
    user_honorific_zh = user_honorific
    agent_self_ref_zh = agent_self_ref
    
    # Mapping dictionaries for wuxia
    zh_wuxia_mapping = {
        "Sư huynh": "师兄",
        "Sư tỷ": "师姐",
        "Đệ đệ": "师弟",
        "Sư đệ": "师弟",
        "Muội muội": "妹妹",
        "Sư muội": "师妹",
        "Tỷ tỷ": "姐姐",
        "Đồng môn": "同门",
        "Đệ tử": "徒儿",
        "Sư phụ": "为师",
        "Nữ Sư Phụ": "为师",
    }
    vi_wuxia_mapping = {
        "师兄": "Sư huynh",
        "师姐": "Sư tỷ",
        "师弟": "Đệ đệ",
        "师妹": "Muội muội",
        "妹妹": "Muội muội",
        "姐姐": "Tỷ tỷ",
        "同门": "Đồng môn",
        "徒儿": "Đệ tử",
        "为师": "Sư phụ",
    }

    if context_setting == "wuxia":
        # 1. Map user_honorific
        if user_honorific in zh_wuxia_mapping:
            user_honorific_zh = zh_wuxia_mapping[user_honorific]
            user_honorific_vi = user_honorific
        else:
            user_honorific_zh = user_honorific
            user_honorific_vi = vi_wuxia_mapping.get(user_honorific, user_honorific)

        # 2. Map agent_self_ref
        if agent_self_ref in zh_wuxia_mapping:
            agent_self_ref_zh = zh_wuxia_mapping[agent_self_ref]
            agent_self_ref_vi = agent_self_ref
        else:
            agent_self_ref_zh = agent_self_ref
            agent_self_ref_vi = vi_wuxia_mapping.get(agent_self_ref, agent_self_ref)
    else:
        # Modern & Academic: user_honorific and agent_self_ref are Vietnamese strings.
        # Map them to standard Chinese pronouns for Chinese target_text.
        if user_honorific in ("Anh", "Chị", "Em", "Bạn"):
            user_honorific_zh = "你"
        elif user_honorific in ("Cô", "Thầy"):
            user_honorific_zh = "您"
        else:
            user_honorific_zh = "你"
            
        if agent_self_ref in ("Em", "Chị", "Mình", "Tôi"):
            agent_self_ref_zh = "我"
        elif agent_self_ref == "Cô":
            agent_self_ref_zh = "老师"
        else:
            agent_self_ref_zh = "我"

    # Retrieve history
    conversation_history = await redis_client.get_conversation_history(user_id, limit=settings.MAX_HISTORY_TURNS, persona_id=persona_id)

    # Build prompt instructions using the dynamic persona parameters
    from prompts import get_system_instruction
    system_instruction = get_system_instruction(
        agent_name=agent_name,
        personality_desc=personality_desc,
        user_honorific_zh=user_honorific_zh,
        agent_self_ref_zh=agent_self_ref_zh,
        user_honorific_vi=user_honorific_vi,
        agent_self_ref_vi=agent_self_ref_vi,
        joy_current=joy_current,
        sad_current=sad_current,
        joy_sensitivity=joy_sensitivity,
        sad_sensitivity=sad_sensitivity,
        learning_language=learning_language,
        context_setting=context_setting,
        user_level=user_level,
        user_name=user_name,
        relation_type=relation_type,
    )

    past_context = payload.get("past_context", "")
    if past_context:
        system_instruction += f"\n\n### PAST CONVERSATION CONTEXT\n{past_context}"


    # Prepare history for Gemini API
    history = agent._format_conversation_history(conversation_history, learning_language=learning_language)
    history.append(
        types.Content(
            role="user",
            parts=[types.Part(text=user_text)]
        )
    )

    # Configure generation parameters
    config = types.GenerateContentConfig(
        temperature=0.9,
        top_p=0.95,
        top_k=40,
        max_output_tokens=2048,
        response_mime_type="application/json",
        response_schema=agent.RESPONSE_SCHEMA,
        system_instruction=system_instruction
    )

    # Save user message to Redis memory
    await redis_client.add_to_conversation_history(user_id, {"role": "user", "content": user_text}, persona_id=persona_id)

    # Keep track of full raw response to parse at the end
    full_response_text = ""
    client = await redis_client.get_client()

    # Per-user binary audio channel
    audio_channel = f"ws:audio:{user_id}"

    try:
        # Call streaming content from Gemini Client (Vertex AI)
        response_stream = await agent.client.aio.models.generate_content_stream(
            model=agent.model_name,
            contents=history,
            config=config
        )

        parser = StreamTutorParser()
        usage = None

        # Queue for sequential TTS synthesis jobs
        tts_queue = asyncio.Queue()

        class _AudioPushCallback(speechsdk.audio.PushAudioOutputStreamCallback):
            def __init__(self):
                super().__init__()
                self.audio_data = bytearray()

            def write(self, audio_buffer: memoryview) -> int:
                self.audio_data.extend(audio_buffer)
                return audio_buffer.nbytes

            def close(self):
                pass

        async def tts_worker():
            try:
                while True:
                    job = await tts_queue.get()
                    if job is None:
                        tts_queue.task_done()
                        break
                    
                    sentence, emotion = job
                    try:
                        # Signal: audio sentence start
                        await _publish_json(client, user_id, "audio_sentence_start", {
                            "text": sentence,
                            "persona_id": persona_id,
                        })

                        if speech_config is not None:
                            presets_dict = get_voice_presets(learning_language)
                            preset = presets_dict.get(emotion, presets_dict["neutral"])
                            voice = preset["voice"]
                            rate = preset["rate"]
                            volume = preset["volume"]
                            
                            tts_text = _sanitize_text_for_audio(sentence, learning_language)
                            
                            # Skip TTS synthesis for Chinese mode if no Chinese characters are present
                            if learning_language == "zh" and not any('\u4e00' <= char <= '\u9fff' for char in tts_text):
                                logger.info(f"Skipping TTS for sentence (no Chinese characters): '{sentence}'")
                                continue
                                
                            xml_lang = 'en-US' if learning_language == 'en' else 'zh-CN'
                            ssml = f"""<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='{xml_lang}'>
                                <voice name='{voice}'>
                                    <prosody rate='{rate}' volume='{volume}'>
                                        {tts_text}
                                    </prosody>
                                </voice>
                            </speak>"""
                            
                            push_callback = _AudioPushCallback()
                            push_stream = speechsdk.audio.PushAudioOutputStream(push_callback)
                            audio_output_config = speechsdk.audio.AudioOutputConfig(stream=push_stream)
                            synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=audio_output_config)
                            
                            result_future = synthesizer.speak_ssml_async(ssml)
                            synthesis_result = await asyncio.to_thread(result_future.get)
                            
                            if synthesis_result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
                                audio_bytes = bytes(push_callback.audio_data)
                                chunk_size = 4096
                                for i in range(0, len(audio_bytes), chunk_size):
                                    await client.publish(audio_channel, audio_bytes[i:i + chunk_size])
                            elif synthesis_result.reason == speechsdk.ResultReason.Canceled:
                                cancellation = synthesis_result.cancellation_details
                                logger.error(f"Speech synthesis canceled: {cancellation.reason} - {cancellation.error_details}")
                        else:
                            logger.warning("Azure Speech Config is not initialized. Skipping audio generation.")
                    except Exception as tts_err:
                        logger.error(f"Azure Speech Synthesis failed for sentence '{sentence}': {tts_err}")
                    finally:
                        # Signal: audio sentence end
                        await _publish_json(client, user_id, "audio_sentence_end", {
                            "text": sentence,
                            "persona_id": persona_id,
                        })
                        tts_queue.task_done()
            except asyncio.CancelledError:
                pass

        # Start background worker task
        worker_task = asyncio.create_task(tts_worker())

        # Iterate over stream chunks asynchronously
        async for chunk in response_stream:
            chunk_text = chunk.text
            full_response_text += chunk_text
            if chunk.usage_metadata:
                usage = chunk.usage_metadata

            # Feed to the JSON parser to detect completed sentences
            for sentence, emotion in parser.feed(chunk_text):
                # Publish text chunk via ws:notifications (JSON)
                await _publish_json(client, user_id, "ai_chat_chunk", {
                    "text": sentence,
                    "emotion": emotion,
                    "is_final": False,
                    "persona_id": persona_id,
                })
                logger.info(f"Published sentence chunk: '{sentence}' with emotion '{emotion}'")

                # Put sentence job into queue
                await tts_queue.put((sentence, emotion))

        # Wait for TTS queue processing to complete
        await tts_queue.put(None)
        await worker_task

        # Parse full generated JSON response
        import json_repair
        result = json_repair.loads(full_response_text)
        
        # Save assistant content to Redis memory
        await redis_client.add_to_conversation_history(user_id, {"role": "assistant", "content": json.dumps(result, ensure_ascii=False)}, persona_id=persona_id)

        # Calculate dynamic emotion state and decay
        active_joy = result.get("active_joy")
        active_sad = result.get("active_sad")
        
        if active_joy is None:
            active_joy = joy_current
        else:
            active_joy = float(active_joy)
            
        if active_sad is None:
            active_sad = sad_current
        else:
            active_sad = float(active_sad)

        # Apply decay to determine the stored state for the next turn
        joy_stored = max(0.0, min(1.0, active_joy * (1.0 - joy_decay_rate)))
        sad_stored = max(0.0, min(1.0, active_sad * (1.0 - sad_decay_rate)))

        # Persist updated emotional state in Redis
        await client.set(f"chat:emotion:{user_id}:{persona_id}" if persona_id else f"chat:emotion:{user_id}", json.dumps({"joy": joy_stored, "sad": sad_stored}))
        logger.info(f"Updated emotion state for user {user_id} (persona {persona_id}): active_joy={active_joy} (stored: {joy_stored}), active_sad={active_sad} (stored: {sad_stored})")

        # Inject token usage metadata
        if usage:
            result["usage_metadata"] = {
                "prompt_token_count": usage.prompt_token_count,
                "candidates_token_count": usage.candidates_token_count,
                "total_token_count": usage.total_token_count
            }

        # Send final completion event
        await _publish_json(client, user_id, "ai_chat_complete", {
            "is_final": True,
            "response": result,
            "active_joy": active_joy,
            "active_sad": active_sad,
            "persona_id": persona_id,
        })
        logger.info(f"Published final chat complete response for user {user_id} (persona {persona_id})")

        # ── Dispatch Celery task for chat EXP calculation ──
        message_id = str(uuid.uuid4())
        is_reward_str = result.get("is_reward", "neutral")
        
        exp_payload = {
            "message_id": message_id,
            "user_id": user_id,
            "lang": learning_language,
            "relation_type": relation_type,
            "is_reward": is_reward_str,
            "joy": active_joy,
            "sad": active_sad,
            "persona_id": persona_id,
        }
        
        try:
            await _dispatch_celery_task(
                client, 
                "apps.gamification.tasks.process_chat_exp", 
                [exp_payload],
                queue_name="queue_chat"
            )
            logger.info(f"Dispatched process_chat_exp Celery task for message_id={message_id}")
        except Exception as dispatch_err:
            logger.error(f"Failed to dispatch process_chat_exp task: {dispatch_err}", exc_info=True)

    except Exception as e:
        logger.error(f"Error streaming AI response: {e}", exc_info=True)
        
        # Check if it is a 429 / resource exhausted error
        is_rate_limit = "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e)
        
        # Remove user message from Redis history (so it's not saved/shown)
        redis_key = f"chat:history:{user_id}:{persona_id}" if persona_id else f"chat:history:{user_id}"
        try:
            await client.rpop(redis_key)
            logger.info(f"Popped failed user message from Redis key: {redis_key}")
        except Exception as pop_err:
            logger.error(f"Failed to pop user message: {pop_err}")

        # Publish error fallback
        fallback = agent._get_fallback_response(user_text, 0)
        if is_rate_limit:
            fallback["target_text"] = "系统繁忙，请稍后再试 (Hệ thống đang bận, vui lòng thử lại sau)"
            fallback["translation_hint"] = "Hệ thống AI đang quá tải (Lỗi 429). Điểm của bạn đã được hoàn lại!"
            fallback["emotion"] = "concerned"
            
        fallback["active_joy"] = joy_current
        fallback["active_sad"] = sad_current
        
        await _publish_json(client, user_id, "ai_chat_complete", {
            "is_final": True,
            "response": fallback,
            "active_joy": joy_current,
            "active_sad": sad_current,
            "persona_id": persona_id,
            "error_code": "429" if is_rate_limit else "500"
        })

        # Trigger coin refund via Celery queue_chat
        coin_group_id = payload.get("coin_group_id")
        coin_lang = payload.get("coin_lang")
        coin_cost = payload.get("coin_cost", 0)
        
        if coin_group_id and coin_lang and coin_cost > 0:
            try:
                import base64
                task_name = "apps.xiaoyue_chat.tasks.refund_chat_coins"
                task_args = [user_id, coin_lang, coin_cost, coin_group_id]
                task_kwargs = {"note": f"Refund: AI Service Error ({'RateLimit 429' if is_rate_limit else 'General Error'})"}
                
                body_data = [task_args, task_kwargs, {"callbacks": None, "errbacks": None, "chain": None, "chord": None}]
                body_str = json.dumps(body_data)
                body_b64 = base64.b64encode(body_str.encode('utf-8')).decode('utf-8')
                
                celery_id = str(uuid.uuid4())
                celery_payload = {
                    "headers": {
                        "lang": "py",
                        "task": task_name,
                        "id": celery_id,
                        "root_id": celery_id,
                        "parent_id": None,
                        "group": None,
                        "meth": None,
                        "shadow": None,
                        "eta": None,
                        "expires": None,
                        "retries": 0,
                        "timelimit": [None, None],
                        "argsrepr": repr(task_args),
                        "kwargsrepr": repr(task_kwargs),
                        "origin": "ai_chat_service"
                    },
                    "properties": {
                        "correlation_id": celery_id,
                        "reply_to": "",
                        "delivery_mode": 2,
                        "delivery_info": {
                            "exchange": "",
                            "routing_key": "queue_chat"
                        },
                        "priority": 0,
                        "body_encoding": "base64"
                    },
                    "content-encoding": "utf-8",
                    "content-type": "application/json",
                    "body": body_b64
                }
                
                # Push task to Redis list queue_chat
                await client.rpush("queue_chat", json.dumps(celery_payload))
                logger.info(f"Successfully triggered Celery refund task for user {user_id} (group={coin_group_id})")
            except Exception as refund_err:
                logger.error(f"Failed to publish Celery refund task: {refund_err}", exc_info=True)


async def start_redis_listener():
    """
    Subscribes to 'ai:chat:request:*' channels using psubscribe.
    Runs indefinitely to handle incoming requests.
    """
    logger.info("Initializing AI Agent and Redis connection...")
    redis_client = RedisClient()
    agent = ChineseTutorAgent()
    
    while True:
        try:
            client = await redis_client.get_client()
            pubsub = client.pubsub()
            
            # Use psubscribe to listen to all user chat request channels
            await pubsub.psubscribe("ai:chat:request:*")
            logger.info("✅ Subscribed to Redis channels pattern: 'ai:chat:request:*'")

            async for message in pubsub.listen():
                if message["type"] != "pmessage":
                    continue
                
                try:
                    payload = json.loads(message["data"])
                    logger.info(f"Received request from Redis: {payload}")
                    
                    # Spawn task to process request without blocking the listener loop
                    asyncio.create_task(process_chat_request(redis_client, agent, payload))
                    
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON in request: {message['data']}")
                except Exception as e:
                    logger.error(f"Error handling request message: {e}")

        except Exception as e:
            logger.error(f"Redis connection error in listener: {e}. Reconnecting in 3s...")
            await asyncio.sleep(3)
