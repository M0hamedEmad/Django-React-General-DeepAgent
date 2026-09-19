import uuid

from django.conf import settings
from django.db import models


def new_id():
    return uuid.uuid4().hex


class UserWorkspace(models.Model):
    """Stable, non-sequential workspace identity for one Django user."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="agent_workspace",
    )

    def __str__(self):
        return self.id.hex


class Thread(models.Model):
    """One conversation. The messages live in the LangGraph checkpointer under
    this id; this row only ties the thread to a user for the sidebar."""

    id = models.CharField(primary_key=True, max_length=64, default=new_id)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="chat_threads"
    )
    title = models.CharField(max_length=200, blank=True)
    # Composer choices belong to the conversation. Restoring them when a
    # thread opens keeps the model/tool prompt prefix stable for cache reuse.
    options = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [
            models.Index(
                fields=["user", "-updated_at"],
                name="da_thread_user_updated_idx",
            )
        ]

    def __str__(self):
        return self.title or self.id

    def as_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "options": self.options,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
