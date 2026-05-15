from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("deep_agent_app", "0002_thread_options")]

    operations = [
        migrations.AddIndex(
            model_name="thread",
            index=models.Index(
                fields=["user", "-updated_at"],
                name="da_thread_user_updated_idx",
            ),
        ),
    ]
