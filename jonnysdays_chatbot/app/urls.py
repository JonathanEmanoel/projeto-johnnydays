from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ClientViewSet, LocutorViewSet, StudioViewSet, BookingViewSet
from django.urls import path
from .views import whatsapp_webhook
from django.http import HttpResponse

router = DefaultRouter()
router.register(r'clients', ClientViewSet)
router.register(r'locutors', LocutorViewSet)
router.register(r'studios', StudioViewSet)
router.register(r'bookings', BookingViewSet)

urlpatterns = [
    path('api/', include(router.urls)),
    path('whatsapp/', whatsapp_webhook, name='whatsapp_webhook'),  # Webhook para lidar com as mensagens do WhatsApp
    path('test/', lambda request: HttpResponse("Rota de teste funcionando"), name='test_route'),  # Rota de teste
]
