import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("deep_agent_app", "0003_thread_user_updated_index"),
    ]

    operations = [
        migrations.CreateModel(
            name="UserWorkspace",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="agent_workspace",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
    ]
