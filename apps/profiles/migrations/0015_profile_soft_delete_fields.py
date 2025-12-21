from django.db import migrations, models


def mark_existing_gifts_as_granted(apps, schema_editor) -> None:
    Profile = apps.get_model("profiles", "Profile")
    Profile.objects.filter(status__in=["completed", "deleted"]).update(gift_credits_granted=True)


class Migration(migrations.Migration):
    dependencies = [
        ("profiles", "0014_profile_height"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="gift_credits_granted",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="profile",
            name="deleted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(mark_existing_gifts_as_granted, migrations.RunPython.noop),
    ]
