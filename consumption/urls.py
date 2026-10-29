from django.urls import path

from . import views

app_name = "consumption"

# Student 2 : ajouter ici les URL du module (listes, formulaires, imports CSV...).
urlpatterns = [
    path("compteurs/", views.meter_list, name="meter_list"),
    path("compteurs/<int:pk>/", views.meter_detail, name="meter_detail"),
    path("compteurs/<int:pk>/importer/", views.meter_import, name="meter_import"),
]
