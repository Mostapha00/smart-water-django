from django.urls import path

from .views import IncidentDetailView, IncidentListView, QualityTestListView, incident_resolve

app_name = "quality_leaks"
urlpatterns = [
    path("incidents/", IncidentListView.as_view(), name="incident_list"),
    path("incidents/<int:pk>/", IncidentDetailView.as_view(), name="incident_detail"),
    path("incidents/<int:pk>/resoudre/", incident_resolve, name="incident_resolve"),
    path("tests/", QualityTestListView.as_view(), name="test_list"),
]
