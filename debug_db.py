import os
import django
import sys

# Add the project root to sys.path
sys.path.append('/app')

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from apps.workout_plans.models import Program

print("Checking programs for client_profile_id=1")
try:
    count = Program.objects.filter(client_profile_id=1).count()
    print(f"Count: {count}")

    latest = Program.objects.filter(client_profile_id=1).order_by("-created_at").first()
    if latest:
        print(f"Latest ID: {latest.id}")
        print(f"Latest Created: {latest.created_at}")
        import json
        print(f"Data: {json.dumps(latest.exercises_by_day, indent=2)}")
    else:
        print("Latest: None")

    all_ids = list(Program.objects.filter(client_profile_id=1).values_list('id', flat=True))
    print(f"All IDs: {all_ids}")
except Exception as e:
    print(f"Error: {e}")
