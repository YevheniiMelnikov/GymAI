from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("profiles", "0003_clientprofile_credits"),
    ]

    operations = [
        migrations.AddField(
            model_name="coachprofile",
            name="coach_type",
            field=models.CharField(
                max_length=10,
                choices=[("human", "human"), ("ai_coach", "ai_coach")],
                default="human",
            ),
        ),
    ]
