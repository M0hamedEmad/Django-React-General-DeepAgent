from django.contrib import admin
from django.urls import path, include

from deep_agent_app import health

urlpatterns = [
    path("health/live/", health.live, name="health-live"),
    path("health/ready/", health.ready, name="health-ready"),
    path("admin/", admin.site.urls),
    path("accounts/", include("django.contrib.auth.urls")),
    path("", include("deep_agent_app.urls")),
]
