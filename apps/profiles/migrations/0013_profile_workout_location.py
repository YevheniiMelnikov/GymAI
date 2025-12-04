from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("profiles", "0012_remove_profile_name"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="workout_location",
            field=models.CharField(
                blank=True,
                choices=[("gym", "gym"), ("home", "home")],
                max_length=32,
                null=True,
            ),
        ),
    ]
