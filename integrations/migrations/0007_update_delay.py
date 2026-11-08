from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("integrations", "0006_large_source_schedule")]

    operations = [
        migrations.AddField(
            model_name="integration",
            name="last_update_delay_seconds",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
    ]
