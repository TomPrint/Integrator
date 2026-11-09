from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("integrations", "0008_termsacceptance"),
    ]

    operations = [
        migrations.AddField(
            model_name="customerprofile",
            name="trial_started_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="customerprofile",
            name="trial_ended_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="customerprofile",
            name="plan",
            field=models.CharField(
                choices=[("basic", "Podstawowy"), ("plus", "Plus"), ("trial", "Testowy (7 dni)")],
                default="basic",
                max_length=10,
            ),
        ),
    ]
