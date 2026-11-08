from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("integrations", "0005_customerprofile_company_name")]

    operations = [
        migrations.AddField(
            model_name="integration",
            name="source_size_bytes",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="integration",
            name="interval_auto_adjusted",
            field=models.BooleanField(default=False),
        ),
        migrations.AlterField(
            model_name="integration",
            name="interval_hours",
            field=models.PositiveIntegerField(
                choices=[(2, "Co 2 godziny"), (4, "Co 4 godziny"), (8, "Co 8 godzin"),
                         (12, "Co 12 godzin"), (24, "Co 24 godziny"), (48, "Co 48 godzin"),
                         (168, "Raz na tydzień")],
                default=12,
            ),
        ),
    ]
