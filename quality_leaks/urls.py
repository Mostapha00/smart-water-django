from django.urls import path

from .views import IncidentDetailView, IncidentListView, QualityTestListView

app_name = "quality_leaks"
urlpatterns = [
    path("incidents/", IncidentListView.as_view(), name="incident_list"),
    path("incidents/<int:pk>/", IncidentDetailView.as_view(), name="incident_detail"),
    path("tests/", QualityTestListView.as_view(), name="test_list"),
]
