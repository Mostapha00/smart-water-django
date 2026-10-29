from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect
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


@login_required
def incident_resolve(request, pk):
    if request.method != "POST":
        return redirect("quality_leaks:incident_detail", pk=pk)
    incident = get_object_or_404(LeakIncident, pk=pk)
    incident.resolve()
    messages.success(request, f"L'incident {incident.reference} est résolu.")
    return redirect("quality_leaks:incident_detail", pk=pk)
