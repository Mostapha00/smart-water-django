from django.urls import path

from . import views

app_name = "consumption"

# Student 2 : ajouter ici les URL du module (listes, formulaires, imports CSV...).
urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("compteurs/", views.meter_list, name="meter_list"),
    path("compteurs/nouveau/", views.meter_create, name="meter_create"),
    path("compteurs/<int:pk>/", views.meter_detail, name="meter_detail"),
    path("releves/nouveau/", views.reading_create, name="reading_create"),
    path("compteurs/<int:pk>/importer/", views.meter_import, name="meter_import"),
    path("tarifs/", views.tariff_list, name="tariff_list"),
    path("tarifs/nouveau/", views.tariff_create, name="tariff_create"),
    path("factures/", views.bill_list, name="bill_list"),
    path("factures/nouvelle/", views.bill_create, name="bill_create"),
]
