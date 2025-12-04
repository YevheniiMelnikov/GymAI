from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("profiles", "0011_remove_profile_profile_photo"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="profile",
            name="name",
        ),
    ]
