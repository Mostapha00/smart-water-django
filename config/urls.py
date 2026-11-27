from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="infrastructure:site_list", permanent=False)),
    path("admin/", admin.site.urls),
    path("", include("accounts.urls")),  # connexion/, inscription/, deconnexion/
    path("infrastructure/", include("infrastructure.urls")),
    path("consommation/", include("consumption.urls")),
    path("qualite-fuites/", include("quality_leaks.urls")),
    path("durabilite/", include("sustainability.urls")),
]
