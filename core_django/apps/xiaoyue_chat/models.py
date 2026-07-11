import logging
from django.db import models
from django.conf import settings
from pgvector.django import VectorField

logger = logging.getLogger(__name__)


class ChatMessage(models.Model):
    """
    Model to persist older chat messages when they are evicted from the active Redis history.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="chat_messages",
        db_index=True,
    )
    role = models.CharField(
        max_length=20,
        help_text="Role of the sender: 'user' or 'assistant'",
    )
    content = models.TextField(
        help_text="The text content of the message",
    )
    timestamp = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
    )

    class Meta:
        ordering = ["timestamp"]
        indexes = [
            models.Index(fields=["user", "timestamp"]),
        ]

    def __str__(self) -> str:
        return f"{self.user.username} - {self.role}: {self.content[:30]}"


class ChatSummary(models.Model):
    """
    Stores periodic conversation summaries with vector embeddings
    for RAG-based context retrieval.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="chat_summaries",
        db_index=True,
    )
    summary_text = models.TextField(
        help_text="Summarized conversation text (max 3 sentences)"
    )
    embedding = VectorField(
        dimensions=768,
        help_text="Vector embedding from text-embedding-004",
        null=True,
    )
    message_count = models.IntegerField(
        default=6,
        help_text="Number of messages summarized in this entry"
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.user.username} - Summary: {self.summary_text[:30]}"

