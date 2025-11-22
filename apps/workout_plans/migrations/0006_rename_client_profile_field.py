from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("workout_plans", "0005_alter_program_profile"),
    ]

    operations = [
        migrations.RenameField(
            model_name="program",
            old_name="client_profile",
            new_name="profile",
        ),
        migrations.RenameField(
            model_name="subscription",
            old_name="client_profile",
            new_name="profile",
        ),
    ]
