from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.generic import CreateView, DetailView, ListView

from .forms import AlertRuleForm, LeakIncidentForm, WaterQualityTestForm
from .models import AlertRule, LeakIncident, WaterQualityTest


@login_required
def dashboard(request):
    return render(request, "quality_leaks/dashboard.html", {
        "active_incidents": LeakIncident.objects.filter(status="investigation").count(),
        "resolved_incidents": LeakIncident.objects.filter(status="resolved").count(),
        "quality_tests": WaterQualityTest.objects.count(),
        "critical_rules": AlertRule.objects.filter(active=True, severity="critical").count(),
    })


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
    if request.method == "POST":
        incident = get_object_or_404(LeakIncident, pk=pk)
        incident.resolve()
        messages.success(request, f"L'incident {incident.reference} est résolu.")
    return redirect("quality_leaks:incident_detail", pk=pk)


class QualityTestCreateView(LoginRequiredMixin, CreateView):
    model = WaterQualityTest
    form_class = WaterQualityTestForm
    template_name = "quality_leaks/form.html"
    success_url = reverse_lazy("quality_leaks:test_list")

    def form_valid(self, form):
        response = super().form_valid(form)
        self.object.classify_potability()
        return response


class IncidentCreateView(LoginRequiredMixin, CreateView):
    model = LeakIncident
    form_class = LeakIncidentForm
    template_name = "quality_leaks/form.html"
    success_url = reverse_lazy("quality_leaks:incident_list")


class RuleCreateView(LoginRequiredMixin, CreateView):
    model = AlertRule
    form_class = AlertRuleForm
    template_name = "quality_leaks/form.html"
    success_url = reverse_lazy("quality_leaks:rule_list")


quality_test_create = QualityTestCreateView.as_view()
incident_create = IncidentCreateView.as_view()
rule_create = RuleCreateView.as_view()


@login_required
def rule_list(request):
    return render(request, "quality_leaks/rule_list.html", {"rules": AlertRule.objects.all()})
