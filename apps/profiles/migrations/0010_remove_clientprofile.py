from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("profiles", "0009_merge_clientprofile"),
        ("workout_plans", "0005_alter_program_profile"),
        ("payments", "0003_alter_payment_profile"),
    ]

    operations = [
        migrations.DeleteModel(
            name="ClientProfile",
        ),
    ]
