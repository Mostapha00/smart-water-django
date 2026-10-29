from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="infrastructure:site_list", permanent=False)),
    path("admin/", admin.site.urls),
    path("connexion/", auth_views.LoginView.as_view(template_name="registration/login.html"), name="login"),
    path("deconnexion/", auth_views.LogoutView.as_view(), name="logout"),
    path("comptes/", include("accounts.urls")),
    path("infrastructure/", include("infrastructure.urls")),
    path("consommation/", include("consumption.urls")),
    path("qualite-fuites/", include("quality_leaks.urls")),
]
