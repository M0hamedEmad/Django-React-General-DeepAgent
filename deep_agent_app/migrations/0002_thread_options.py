from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("deep_agent_app", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="thread",
            name="options",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
