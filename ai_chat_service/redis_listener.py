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
    if not user_id or not user_text:
        logger.warning(f"Invalid chat request payload: {payload}")
        return

    user_role = payload.get("user_role", "Sư huynh")
    user_level = payload.get("user_level", "Beginner")
    topic = payload.get("topic", "Daily Conversation")
    user_name = payload.get("user_name", user_role)
    learning_language = payload.get("learning_language", "zh")
    context_setting = payload.get("context_setting", "wuxia")

    # Determine agent role and personality based on role mapping
    relationship = ROLE_RELATIONSHIPS.get(user_role, ROLE_RELATIONSHIPS["Sư huynh"])
    agent_role = relationship["agent_role"]
    sulking_enabled = relationship["sulking_enabled"]

    # Retrieve state and history
    sulking_level = await redis_client.get_sulking_level(user_id)
    conversation_history = await redis_client.get_conversation_history(user_id, limit=settings.MAX_HISTORY_TURNS)

    # Build prompt instructions
    from prompts import get_system_instruction
    system_instruction = get_system_instruction(
        user_role=user_role,
        agent_role=agent_role,
        sulking_level=sulking_level,
        user_level=user_level,
        topic=topic,
        user_name=user_name,
        learning_language=learning_language,
        context_setting=context_setting
    )

    past_context = payload.get("past_context", "")
    if past_context:
        system_instruction += f"\n\n### PAST CONVERSATION CONTEXT\n{past_context}"


    # Prepare history for Gemini API
    history = agent._format_conversation_history(conversation_history)
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
    await redis_client.add_to_conversation_history(user_id, {"role": "user", "content": user_text})

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
                })
                logger.info(f"Published sentence chunk: '{sentence}' with emotion '{emotion}'")

                # Signal: audio sentence start
                await _publish_json(client, user_id, "audio_sentence_start", {
                    "text": sentence,
                })

                # Stream binary audio chunks via Azure Speech SDK
                if speech_config is not None:
                    try:
                        presets_dict = get_voice_presets(learning_language)
                        preset = presets_dict.get(emotion, presets_dict["neutral"])
                        voice = preset["voice"]
                        rate = preset["rate"]
                        volume = preset["volume"]
                        
                        tts_text = _sanitize_text_for_audio(sentence)
                        xml_lang = 'en-US' if learning_language == 'en' else 'zh-CN'
                        
                        # Construct SSML representation
                        ssml = f"""<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='{xml_lang}'>
                            <voice name='{voice}'>
                                <prosody rate='{rate}' volume='{volume}'>
                                    {tts_text}
                                </prosody>
                            </voice>
                        </speak>"""
                        
                        # Use PushAudioOutputStream with a callback to capture audio data
                        class _AudioPushCallback(speechsdk.audio.PushAudioOutputStreamCallback):
                            def __init__(self):
                                super().__init__()
                                self.audio_data = bytearray()

                            def write(self, audio_buffer: memoryview) -> int:
                                self.audio_data.extend(audio_buffer)
                                return audio_buffer.nbytes

                            def close(self):
                                pass

                        push_callback = _AudioPushCallback()
                        push_stream = speechsdk.audio.PushAudioOutputStream(push_callback)
                        audio_output_config = speechsdk.audio.AudioOutputConfig(stream=push_stream)
                        
                        # Synthesizer instance for this task
                        synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=audio_output_config)
                        
                        # Speak SSML and wait for completion
                        result_future = synthesizer.speak_ssml_async(ssml)
                        synthesis_result = await asyncio.to_thread(result_future.get)
                        
                        if synthesis_result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
                            # Publish collected audio data in chunks to Redis
                            audio_bytes = bytes(push_callback.audio_data)
                            chunk_size = 4096
                            for i in range(0, len(audio_bytes), chunk_size):
                                await client.publish(audio_channel, audio_bytes[i:i + chunk_size])
                        elif synthesis_result.reason == speechsdk.ResultReason.Canceled:
                            cancellation = synthesis_result.cancellation_details
                            logger.error(f"Speech synthesis canceled: {cancellation.reason} - {cancellation.error_details}")
                            
                    except Exception as tts_err:
                        logger.error(f"Azure Speech Synthesis failed for sentence '{sentence}': {tts_err}")
                else:
                    logger.warning("Azure Speech Config is not initialized. Skipping audio generation.")

                # Signal: audio sentence end
                await _publish_json(client, user_id, "audio_sentence_end", {
                    "text": sentence,
                })

        # Parse full generated JSON response
        import json_repair
        result = json_repair.loads(full_response_text)
        
        # Save assistant content to Redis memory
        await redis_client.add_to_conversation_history(user_id, {"role": "assistant", "content": result.get("target_text", "")})

        # Dynamically adjust sulking level if enabled
        action = result.get("action", "none")
        if sulking_enabled:
            if action == "correction":
                await redis_client.decrement_sulking_level(user_id)
            else:
                import random
                if random.random() < 0.15:
                    await redis_client.increment_sulking_level(user_id)

        # Inject token usage metadata
        if usage:
            result["usage_metadata"] = {
                "prompt_token_count": usage.prompt_token_count,
                "candidates_token_count": usage.candidates_token_count,
                "total_token_count": usage.total_token_count
            }

        # Fetch updated sulking level
        new_sulking = await redis_client.get_sulking_level(user_id)

        # Send final completion event
        await _publish_json(client, user_id, "ai_chat_complete", {
            "is_final": True,
            "response": result,
            "sulking_level": new_sulking,
        })
        logger.info(f"Published final chat complete response for user {user_id}")

    except Exception as e:
        logger.error(f"Error streaming AI response: {e}", exc_info=True)
        # Publish error fallback
        fallback = agent._get_fallback_response(user_text, sulking_level)
        await _publish_json(client, user_id, "ai_chat_complete", {
            "is_final": True,
            "response": fallback,
        })


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
