from django.urls import path

from . import views
from .views import IncidentDetailView, IncidentListView, QualityTestListView, incident_resolve

app_name = "quality_leaks"
urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("incidents/", IncidentListView.as_view(), name="incident_list"),
    path("incidents/nouveau/", views.incident_create, name="incident_create"),
    path("incidents/<int:pk>/", IncidentDetailView.as_view(), name="incident_detail"),
    path("incidents/<int:pk>/resoudre/", incident_resolve, name="incident_resolve"),
    path("tests/", QualityTestListView.as_view(), name="test_list"),
    path("tests/nouveau/", views.quality_test_create, name="test_create"),
    path("regles/", views.rule_list, name="rule_list"),
    path("regles/nouvelle/", views.rule_create, name="rule_create"),
]
