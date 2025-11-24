from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("profiles", "0007_alter_coachprofile_coach_type"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="clientprofile",
            name="assigned_to",
        ),
        migrations.RemoveField(
            model_name="profile",
            name="role",
        ),
        migrations.DeleteModel(
            name="CoachProfile",
        ),
    ]
