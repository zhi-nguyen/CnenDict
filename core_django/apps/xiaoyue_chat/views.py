import logging

from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from core_project.ws_utils import get_redis_client
from .tasks import dispatch_chat_request

logger = logging.getLogger(__name__)


class XiaoyueChatSendView(APIView):
    """
    Dispatch a chat request to the AI Chat Service via Celery + Redis Pub/Sub.
    Tier-based queue routing is handled by UserTierRouter.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        user_text = request.data.get("user_text", "").strip()
        if not user_text:
            return Response(
                {"detail": "Nội dung tin nhắn không được để trống."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Extract values with fallbacks
        user_role = request.data.get("user_role", "Sư huynh")
        user_level = request.data.get("user_level", "Beginner")
        topic = request.data.get("topic", "Daily Conversation")
        learning_language = request.data.get("learning_language", "zh")
        context_setting = request.data.get("context_setting", "wuxia")

        # Determine user name
        user_name = user.first_name or user.username or user_role

        # Determine user tier for queue routing
        user_tier = (
            getattr(user.subscription, "tier", "Free")
            if hasattr(user, "subscription")
            else "Free"
        )

        # Dispatch to Celery task with tier routing via UserTierRouter
        dispatch_chat_request.apply_async(
            args=[
                str(user.id),
                user_text,
                user_role,
                user_level,
                topic,
                user_name,
            ],
            kwargs={
                "user_tier": user_tier,
                "learning_language": learning_language,
                "context_setting": context_setting,
            },
        )

        return Response(
            {
                "status": "success",
                "message": "Chat request dispatched successfully.",
            },
            status=status.HTTP_202_ACCEPTED,
        )


class XiaoyueChatSulkingView(APIView):
    """
    Get the current sulking level of the authenticated user from Redis.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user_id = str(request.user.id)
        try:
            redis_client = get_redis_client()
            key = f"chat:sulking:{user_id}"
            level = redis_client.get(key)
            sulking_level = int(level) if level else 0
        except Exception as e:
            logger.error(f"Failed to fetch sulking level for user {user_id}: {e}")
            sulking_level = 0

        return Response({
            "user_id": user_id,
            "sulking_level": sulking_level,
        })


class XiaoyueChatClearView(APIView):
    """
    Clear conversation history, reset state counter, reset sulking level, and delete past context summaries.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user_id = str(request.user.id)
        try:
            redis_client = get_redis_client()
            redis_client.delete(f"chat:history:{user_id}")
            redis_client.delete(f"chat:sulking:{user_id}")
            redis_client.delete(f"chat:counter:{user_id}")
            
            # Delete past RAG summaries from database
            from .models import ChatSummary
            ChatSummary.objects.filter(user_id=request.user.id).delete()
            
            logger.info(f"Cleared chat history, counter, and summaries for user {user_id}")
        except Exception as e:
            logger.error(f"Failed to clear chat data for user {user_id}: {e}")
            return Response(
                {"detail": "Không thể xóa lịch sử trò chuyện."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response({
            "status": "success",
            "user_id": user_id,
        })

