from accounts.models import Person
from rest_framework import serializers


class PersonSerializer(serializers.Serializer):
    tg_user_id = serializers.IntegerField()
    short_name = serializers.CharField(max_length=50)
    password = serializers.CharField(max_length=50)
    status = serializers.CharField(max_length=50)
    gender = serializers.CharField(max_length=50, read_only=True)
    birth_date = serializers.DateField(read_only=True)
    language = serializers.CharField(max_length=50, read_only=True)

    def create(self, validated_data):
        return Person.objects.create(**validated_data)

    def update(self, instance, validated_data):
        instance.tg_user_id = validated_data.get("tg_user_id", instance.tg_user_id)
        instance.short_name = validated_data.get("short_name", instance.short_name)
        instance.password = validated_data.get("password", instance.password)
        instance.status = validated_data.get("status", instance.status)
        instance.gender = validated_data.get("gender", instance.gender)
        instance.birth_date = validated_data.get("birth_date", instance.birth_date)
        instance.language = validated_data.get("language", instance.language)
        instance.save()
        return instance

    class Meta:
        model = Person
        fields = ("tg_user_id", "short_name", "password", "status")
