from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("workout_plans", "0007_merge_20251122_2222"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="program",
            index=models.Index(
                fields=["profile", "-created_at"],
                name="program_profile_created_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="subscription",
            index=models.Index(
                fields=["profile", "-updated_at"],
                name="sub_profile_updated_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="subscription",
            index=models.Index(
                fields=["profile"],
                name="sub_active_profile_idx",
                condition=models.Q(("enabled", True)),
            ),
        ),
        migrations.AddIndex(
            model_name="subscription",
            index=models.Index(
                fields=["payment_date"],
                name="sub_paydate_enabled_idx",
                condition=models.Q(("enabled", True)),
            ),
        ),
    ]
