from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.html import format_html
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from .forms import AlertRuleForm, LeakIncidentForm, WaterQualityTestForm
from .models import AlertRule, LeakIncident, WaterQualityTest
from .services import open_quality_incident

MODULE = {"module_label": "Qualité & fuites", "module_url": reverse_lazy("quality_leaks:dashboard")}


class FormPageMixin(PermissionRequiredMixin):
    page_title = ""
    cancel_url = None

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(MODULE, page_title=self.page_title, cancel_url=self.cancel_url or MODULE["module_url"])
        return ctx


@login_required
def dashboard(request):
    return render(request, "quality_leaks/dashboard.html", {
        "active_incidents": LeakIncident.objects.filter(status="investigation").count(),
        "resolved_incidents": LeakIncident.objects.filter(status="resolved").count(),
        "quality_tests": WaterQualityTest.objects.count(),
        "critical_rules": AlertRule.objects.filter(active=True, severity="critical").count(),
        "recent_incidents": LeakIncident.objects.order_by("-opened_at")[:5],
    })


class IncidentListView(LoginRequiredMixin, ListView):
    model = LeakIncident
    template_name = "quality_leaks/incident_list.html"
    context_object_name = "incidents"

    def get_queryset(self):
        qs = LeakIncident.objects.select_related("rule", "technician", "suspected_pipe", "suspected_pump", "trigger_test__zone")
        state = self.request.GET.get("etat")
        if state in ("investigation", "resolved"):
            qs = qs.filter(status=state)
        return qs

    def get_context_data(self, **kwargs):
        return super().get_context_data(state=self.request.GET.get("etat", ""), **kwargs)


class IncidentDetailView(LoginRequiredMixin, DetailView):
    model = LeakIncident
    template_name = "quality_leaks/incident_detail.html"
    context_object_name = "incident"


@login_required
@permission_required("quality_leaks.change_leakincident", raise_exception=True)
@require_POST
def incident_resolve(request, pk):
    incident = get_object_or_404(LeakIncident, pk=pk)
    if incident.status == "resolved":
        messages.info(request, f"L'incident {incident.reference} était déjà résolu.")
    else:
        incident.resolve()
        messages.success(request, f"L'incident {incident.reference} est résolu.")
    return redirect("quality_leaks:incident_detail", pk=pk)


class QualityTestListView(LoginRequiredMixin, ListView):
    model = WaterQualityTest
    template_name = "quality_leaks/test_list.html"
    context_object_name = "tests"

    def get_queryset(self):
        return WaterQualityTest.objects.select_related("zone", "zone__site").order_by("-sampled_at")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        rules = list(AlertRule.objects.filter(active=True))
        ctx["rows"] = [{"test": t, "matched": [r for r in rules if r.evaluate(t)]} for t in ctx["tests"]]
        return ctx


class QualityTestCreateView(FormPageMixin, CreateView):
    permission_required = "quality_leaks.add_waterqualitytest"
    model = WaterQualityTest
    form_class = WaterQualityTestForm
    template_name = "quality_leaks/form.html"
    page_title = "Nouvelle analyse d'eau"
    success_url = cancel_url = reverse_lazy("quality_leaks:test_list")

    def form_valid(self, form):
        response = super().form_valid(form)
        test = self.object
        test.classify_potability()
        matched = test.evaluate_rules()
        incident = open_quality_incident(test, matched)
        if incident:
            messages.error(self.request, format_html(
                "Règle critique enfreinte : l'incident <a href='{}'>{}</a> a été ouvert.",
                incident.get_absolute_url(), incident.reference))
        elif matched:
            messages.warning(self.request, format_html(
                "Analyse enregistrée, mais {} règle(s) d'alerte enfreinte(s) : {}. <a href='{}'>Ouvrir un incident</a>",
                len(matched), ", ".join(r.name for r in matched),
                reverse("quality_leaks:incident_create") + f"?trigger_test={test.pk}"))
        else:
            messages.success(self.request, "Analyse enregistrée : aucune règle d'alerte enfreinte.")
        return response


class IncidentCreateView(FormPageMixin, CreateView):
    permission_required = "quality_leaks.add_leakincident"
    model = LeakIncident
    form_class = LeakIncidentForm
    template_name = "quality_leaks/form.html"
    page_title = "Nouvel incident"
    cancel_url = reverse_lazy("quality_leaks:incident_list")

    def get_initial(self):
        initial = {}
        for key in ("meter", "trigger_test", "suspected_pipe", "suspected_pump"):
            value = self.request.GET.get(key)
            if value and value.isdigit():
                initial[key] = int(value)
        return initial

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f"Incident {self.object.reference} ouvert.")
        return response

    def get_success_url(self):
        return self.object.get_absolute_url()


class IncidentUpdateView(FormPageMixin, UpdateView):
    permission_required = "quality_leaks.change_leakincident"
    model = LeakIncident
    form_class = LeakIncidentForm
    template_name = "quality_leaks/form.html"

    def get_context_data(self, **kwargs):
        self.page_title = f"Modifier l'incident {self.object.reference}"
        self.cancel_url = self.object.get_absolute_url()
        return super().get_context_data(**kwargs)

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Incident mis à jour.")
        return response

    def get_success_url(self):
        return self.object.get_absolute_url()


class RuleCreateView(FormPageMixin, CreateView):
    permission_required = "quality_leaks.add_alertrule"
    model = AlertRule
    form_class = AlertRuleForm
    template_name = "quality_leaks/form.html"
    page_title = "Nouvelle règle d'alerte"
    success_url = cancel_url = reverse_lazy("quality_leaks:rule_list")


class RuleUpdateView(FormPageMixin, UpdateView):
    permission_required = "quality_leaks.change_alertrule"
    model = AlertRule
    form_class = AlertRuleForm
    template_name = "quality_leaks/form.html"
    success_url = cancel_url = reverse_lazy("quality_leaks:rule_list")

    def get_context_data(self, **kwargs):
        self.page_title = f"Modifier la règle « {self.object.name} »"
        return super().get_context_data(**kwargs)


quality_test_create = QualityTestCreateView.as_view()
incident_create = IncidentCreateView.as_view()
incident_update = IncidentUpdateView.as_view()
rule_create = RuleCreateView.as_view()
rule_update = RuleUpdateView.as_view()


@login_required
def rule_list(request):
    return render(request, "quality_leaks/rule_list.html", {"rules": AlertRule.objects.all().order_by("-active", "parameter", "name")})
