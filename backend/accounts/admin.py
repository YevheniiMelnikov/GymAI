from django.contrib import admin

from .models import Person, Subscription

admin.site.register(Person)
admin.site.register(Subscription)
