from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("profiles", "0005_alter_clientprofile_credits_default"),
    ]

    operations = [
        migrations.AddField(
            model_name="coachprofile",
            name="payout_due",
            field=models.DecimalField(max_digits=10, decimal_places=2, default=0),
        ),
    ]
