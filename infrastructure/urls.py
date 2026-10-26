from django.urls import path

from . import views

app_name = "infrastructure"

urlpatterns = [
    # Sites
    path("sites/", views.SiteListView.as_view(), name="site_list"),
    path("sites/nouveau/", views.SiteCreateView.as_view(), name="site_create"),
    path("sites/<int:pk>/", views.SiteDetailView.as_view(), name="site_detail"),
    path("sites/<int:pk>/modifier/", views.SiteUpdateView.as_view(), name="site_update"),
    path("sites/<int:pk>/supprimer/", views.SiteDeleteView.as_view(), name="site_delete"),
    path("sites/<int:pk>/maquette/", views.site_maquette, name="site_maquette"),
    path("sites/<int:pk>/maquette.json", views.site_maquette_json, name="site_maquette_json"),
    # Zones
    path("zones/nouvelle/", views.ZoneCreateView.as_view(), name="zone_create"),
    path("zones/<int:pk>/modifier/", views.ZoneUpdateView.as_view(), name="zone_update"),
    path("zones/<int:pk>/supprimer/", views.ZoneDeleteView.as_view(), name="zone_delete"),
    path("zones/<int:pk>/position/", views.zone_position, name="zone_position"),
    # Canalisations
    path("canalisations/nouvelle/", views.PipeCreateView.as_view(), name="pipe_create"),
    path("canalisations/<int:pk>/", views.PipeDetailView.as_view(), name="pipe_detail"),
    path("canalisations/<int:pk>/modifier/", views.PipeUpdateView.as_view(), name="pipe_update"),
    path("canalisations/<int:pk>/supprimer/", views.PipeDeleteView.as_view(), name="pipe_delete"),
    # Pompes
    path("pompes/nouvelle/", views.PumpCreateView.as_view(), name="pump_create"),
    path("pompes/<int:pk>/", views.PumpDetailView.as_view(), name="pump_detail"),
    path("pompes/<int:pk>/modifier/", views.PumpUpdateView.as_view(), name="pump_update"),
    path("pompes/<int:pk>/supprimer/", views.PumpDeleteView.as_view(), name="pump_delete"),
    # Prédiction IA
    path("equipements/<str:kind>/<int:pk>/predire/", views.equipment_predict, name="equipment_predict"),
    # Maintenance
    path("interventions/", views.WorkListView.as_view(), name="work_list"),
    path("interventions/nouvelle/", views.WorkCreateView.as_view(), name="work_create"),
    path("interventions/<int:pk>/", views.WorkDetailView.as_view(), name="work_detail"),
    path("interventions/<int:pk>/modifier/", views.WorkUpdateView.as_view(), name="work_update"),
    path("interventions/<int:pk>/cloturer/", views.work_close, name="work_close"),
]
