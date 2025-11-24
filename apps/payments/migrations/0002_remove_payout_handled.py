from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0001_initial"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="payment",
            name="payout_handled",
        ),
    ]
