from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import DetailView, ListView

from .models import LeakIncident, WaterQualityTest


class IncidentListView(LoginRequiredMixin, ListView):
    model = LeakIncident
    template_name = "quality_leaks/incident_list.html"
    context_object_name = "incidents"


class IncidentDetailView(LoginRequiredMixin, DetailView):
    model = LeakIncident
    template_name = "quality_leaks/incident_detail.html"
    context_object_name = "incident"


class QualityTestListView(LoginRequiredMixin, ListView):
    model = WaterQualityTest
    template_name = "quality_leaks/test_list.html"
    context_object_name = "tests"
