from django.contrib import admin

from .models import Profile, Program, Subscription

admin.site.register(Profile)
admin.site.register(Subscription)
admin.site.register(Program)
