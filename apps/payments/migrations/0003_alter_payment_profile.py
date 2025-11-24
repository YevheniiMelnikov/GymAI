from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0002_remove_payout_handled"),
        ("profiles", "0009_merge_clientprofile"),
    ]

    operations = [
        migrations.AlterField(
            model_name="payment",
            name="client_profile",
            field=models.ForeignKey(
                on_delete=models.CASCADE,
                related_name="payments",
                to="profiles.profile",
            ),
        ),
    ]
