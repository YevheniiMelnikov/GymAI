from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("workout_plans", "0002_subscription_period"),
    ]

    operations = [
        migrations.AlterField(
            model_name="subscription",
            name="period",
            field=models.CharField(
                max_length=3,
                choices=[("1m", "1 month"), ("6m", "6 months")],
                default="1m",
            ),
        ),
    ]
