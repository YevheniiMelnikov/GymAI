from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("profiles", "0010_remove_clientprofile"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="profile",
            name="profile_photo",
        ),
    ]
