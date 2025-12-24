from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("profiles", "0015_profile_soft_delete_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="diet_allergies",
            field=models.CharField(blank=True, max_length=250, null=True),
        ),
        migrations.AddField(
            model_name="profile",
            name="diet_products",
            field=models.JSONField(blank=True, default=None, null=True),
        ),
    ]
