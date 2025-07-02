from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("workout_plans", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="subscription",
            name="period",
            field=models.CharField(
                max_length=3,
                choices=[("14d", "14 days"), ("1m", "1 month"), ("6m", "6 months")],
                default="1m",
            ),
        ),
    ]
