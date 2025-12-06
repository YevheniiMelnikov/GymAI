from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0004_rename_client_profile_field"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="payment",
            index=models.Index(
                fields=["profile", "payment_type", "-created_at"],
                name="pay_prof_type_created_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="payment",
            index=models.Index(fields=["status"], name="payment_status_idx"),
        ),
    ]
