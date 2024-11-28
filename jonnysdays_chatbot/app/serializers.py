from rest_framework import serializers
from .models import Client, Locutor, Studio, Booking


class ClientSerializer(serializers.ModelSerializer):
    class Meta:
        model = Client
        fields = '__all__'


class LocutorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Locutor
        fields = '__all__'





class StudioSerializer(serializers.ModelSerializer):
    class Meta:
        model = Studio
        fields = '__all__'


class BookingSerializer(serializers.ModelSerializer):
    class Meta:
        model = Booking
        fields = '__all__'
