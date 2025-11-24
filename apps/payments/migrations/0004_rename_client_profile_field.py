from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0003_alter_payment_profile"),
    ]

    operations = [
        migrations.RenameField(
            model_name="payment",
            old_name="client_profile",
            new_name="profile",
        ),
    ]
