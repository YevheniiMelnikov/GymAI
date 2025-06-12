from django.contrib import admin
from .models import Profile, ClientProfile, CoachProfile

admin.site.register(Profile)
admin.site.register(ClientProfile)
admin.site.register(CoachProfile)
