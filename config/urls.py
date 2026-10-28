from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    # Вхід через Google (django-allauth): /accounts/google/login/ тощо
    path('accounts/', include('allauth.urls')),
    path('', include('inventory.urls')),
]