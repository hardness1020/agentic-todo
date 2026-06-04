"""URL configuration for config project."""
from django.contrib import admin
from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView

from accounts.views import RegisterView
from todos.views import TodoViewSet

router = DefaultRouter()
router.register('todos', TodoViewSet, basename='todo')

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/auth/register', RegisterView.as_view(), name='register'),
    path('api/auth/token', TokenObtainPairView.as_view(), name='token_obtain'),
    path('api/', include(router.urls)),
    path('api/', include('agent.urls')),
]
