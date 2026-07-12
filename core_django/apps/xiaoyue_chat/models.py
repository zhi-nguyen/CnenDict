import uuid
import logging
from django.db import models
from django.conf import settings
from pgvector.django import VectorField

logger = logging.getLogger(__name__)


class ChatPersona(models.Model):
    """
    Persisted AI Tutor Personas.
    Each user can create and maintain multiple tutors.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="chat_personas",
        db_index=True,
    )
    agent_name = models.CharField(max_length=100)
    agent_birth_year = models.IntegerField(null=True, blank=True)
    age_diff = models.IntegerField(null=True, blank=True)
    personality_type = models.CharField(max_length=50)  # 'cold', 'cheerful', 'strict', 'gentle'
    personality_desc = models.TextField()
    avatar_emoji = models.CharField(max_length=20)
    avatar_url = models.URLField(max_length=500, null=True, blank=True)
    context_setting = models.CharField(max_length=50)  # 'wuxia', 'modern', 'academic'
    learning_language = models.CharField(max_length=10)  # 'zh', 'en'
    user_level = models.CharField(max_length=50)
    user_honorific = models.CharField(max_length=100)
    agent_self_ref = models.CharField(max_length=100)
    relation_type = models.CharField(max_length=50, default="default")

    # Emotional multipliers
    joy_sensitivity = models.FloatField(default=1.0)
    joy_decay_rate = models.FloatField(default=0.4)
    sad_sensitivity = models.FloatField(default=0.5)
    sad_decay_rate = models.FloatField(default=0.6)

    # Stored emotional state
    joy_current = models.FloatField(default=0.5)
    sad_current = models.FloatField(default=0.1)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["user", "-updated_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.user.username} - Tutor: {self.agent_name} ({self.personality_type})"


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
    persona = models.ForeignKey(
        ChatPersona,
        on_delete=models.CASCADE,
        related_name="messages",
        db_index=True,
        null=True,
        blank=True,
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
            models.Index(fields=["persona", "timestamp"]),
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
    persona = models.ForeignKey(
        ChatPersona,
        on_delete=models.CASCADE,
        related_name="summaries",
        db_index=True,
        null=True,
        blank=True,
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
            models.Index(fields=["persona", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.user.username} - Summary: {self.summary_text[:30]}"

