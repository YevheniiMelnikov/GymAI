from django.db import migrations, models


def convert_exercises(apps, schema_editor):
    Program = apps.get_model("workout_plans", "Program")
    Subscription = apps.get_model("workout_plans", "Subscription")
    for program in Program.objects.all():
        data = program.exercises_by_day
        if isinstance(data, dict):
            program.exercises_by_day = [
                {"day": str(k), "exercises": v} for k, v in sorted(data.items(), key=lambda kv: int(str(kv[0])))
            ]
            program.save(update_fields=["exercises_by_day"])
    for sub in Subscription.objects.all():
        data = sub.exercises
        if isinstance(data, dict):
            sub.exercises = [
                {"day": str(k), "exercises": v} for k, v in sorted(data.items(), key=lambda kv: int(str(kv[0])))
            ]
            sub.save(update_fields=["exercises"])


class Migration(migrations.Migration):
    dependencies = [
        ("workout_plans", "0003_program_coach_type"),
    ]

    operations = [
        migrations.AlterField(
            model_name="program",
            name="exercises_by_day",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AlterField(
            model_name="subscription",
            name="exercises",
            field=models.JSONField(blank=True, default=list, null=True),
        ),
        migrations.RunPython(convert_exercises, migrations.RunPython.noop),
    ]
