from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("workout_plans", "0004_remove_program_coach_type"),
        ("profiles", "0009_merge_clientprofile"),
    ]

    operations = [
        migrations.AlterField(
            model_name="program",
            name="client_profile",
            field=models.ForeignKey(
                on_delete=models.CASCADE,
                related_name="programs",
                to="profiles.profile",
            ),
        ),
        migrations.AlterField(
            model_name="subscription",
            name="client_profile",
            field=models.ForeignKey(
                on_delete=models.CASCADE,
                related_name="subscriptions",
                to="profiles.profile",
            ),
        ),
    ]
