from django.db import migrations, models


def copy_client_profile_data(apps, schema_editor):
    ClientProfile = apps.get_model("profiles", "ClientProfile")
    for client_profile in ClientProfile.objects.all():
        profile = client_profile.profile
        profile.name = client_profile.name
        profile.status = client_profile.status or "initial"
        profile.gender = client_profile.gender
        profile.born_in = client_profile.born_in
        profile.weight = client_profile.weight
        profile.health_notes = client_profile.health_notes
        profile.workout_experience = client_profile.workout_experience
        profile.workout_goals = client_profile.workout_goals
        profile.profile_photo = client_profile.profile_photo
        profile.credits = client_profile.credits or 0
        profile.save()


class Migration(migrations.Migration):
    dependencies = [
        ("profiles", "0008_drop_coachprofile_and_role"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="name",
            field=models.CharField(max_length=50, null=True, blank=True),
        ),
        migrations.AddField(
            model_name="profile",
            name="status",
            field=models.CharField(
                max_length=50,
                choices=[
                    ("waiting_for_text", "waiting_for_text"),
                    ("default", "default"),
                    ("waiting_for_subscription", "waiting_for_subscription"),
                    ("waiting_for_program", "waiting_for_program"),
                    ("initial", "initial"),
                ],
                default="initial",
            ),
        ),
        migrations.AddField(
            model_name="profile",
            name="gender",
            field=models.CharField(max_length=50, null=True, blank=True),
        ),
        migrations.AddField(
            model_name="profile",
            name="born_in",
            field=models.IntegerField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name="profile",
            name="weight",
            field=models.IntegerField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name="profile",
            name="health_notes",
            field=models.CharField(max_length=250, null=True, blank=True),
        ),
        migrations.AddField(
            model_name="profile",
            name="workout_experience",
            field=models.CharField(max_length=50, null=True, blank=True),
        ),
        migrations.AddField(
            model_name="profile",
            name="workout_goals",
            field=models.CharField(max_length=250, null=True, blank=True),
        ),
        migrations.AddField(
            model_name="profile",
            name="profile_photo",
            field=models.CharField(max_length=250, null=True, blank=True),
        ),
        migrations.AddField(
            model_name="profile",
            name="credits",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.RunPython(copy_client_profile_data),
    ]
