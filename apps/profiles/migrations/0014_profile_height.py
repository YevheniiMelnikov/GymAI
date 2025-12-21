from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("profiles", "0013_profile_workout_location"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="height",
            field=models.IntegerField(blank=True, null=True),
        ),
    ]
