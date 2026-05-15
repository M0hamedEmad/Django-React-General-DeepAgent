from django.apps import AppConfig


class DeepAgentAppConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "deep_agent_app"
    verbose_name = "Deep Agent"

    def ready(self):
        # Register project-specific deployment checks without doing I/O.
        from . import checks  # noqa: F401
