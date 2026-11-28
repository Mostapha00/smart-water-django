from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from infrastructure.models import Site

from .forms import ConservationTargetForm, MeasuredBenefitForm, OptimizationRunForm, SustainabilityProjectForm
from .models import AuditReport, ConservationTarget, MeasuredBenefit, OptimizationRun, SustainabilityProject
from .services.dashboard import executive_metrics
from .services.optimization import optimize_projects
from .services.pdf import PdfUnavailable, render_audit_pdf

MODULE = {"module_label": "Durabilité & BI", "module_url": reverse_lazy("sustainability:dashboard")}
LABELS = {  # (singulier, liste) pour les titres de pages
    "conservationtarget": ("cible de conservation", "sustainability:target_list"),
    "sustainabilityproject": ("projet", "sustainability:project_list"),
    "measuredbenefit": ("bénéfice mesuré", "sustainability:benefit_list"),
}


class AuthListView(LoginRequiredMixin, ListView):
    context_object_name = "objects"


class AuthDetailView(LoginRequiredMixin, DetailView):
    pass


class ModelPermissionMixin(PermissionRequiredMixin):
    """Exige la permission Django du modèle : add_<modèle>, change_<modèle> ou delete_<modèle>.

    Les visiteurs non connectés sont redirigés vers la connexion ; un compte sans droit reçoit 403.
    """

    permission_action = ""

    def get_permission_required(self):
        opts = self.model._meta
        return [f"{opts.app_label}.{self.permission_action}_{opts.model_name}"]

    def label(self):
        return LABELS[self.model._meta.model_name]

    def get_success_url(self):
        return reverse_lazy(self.label()[1])

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(MODULE, page_title=self.page_title(), cancel_url=reverse_lazy(self.label()[1]))
        return ctx


class AuthCreateView(ModelPermissionMixin, CreateView):
    permission_action = "add"
    template_name = "sustainability/form.html"

    def page_title(self):
        return f"Nouveau {self.label()[0]}" if self.model is not ConservationTarget else "Nouvelle cible de conservation"

    def form_valid(self, form):
        messages.success(self.request, "Enregistrement créé.")
        return super().form_valid(form)


class AuthUpdateView(ModelPermissionMixin, UpdateView):
    permission_action = "change"
    template_name = "sustainability/form.html"

    def page_title(self):
        return f"Modifier « {self.object} »"

    def get_success_url(self):
        return self.object.get_absolute_url()

    def form_valid(self, form):
        messages.success(self.request, "Modifications enregistrées.")
        return super().form_valid(form)


class AuthDeleteView(ModelPermissionMixin, DeleteView):
    permission_action = "delete"
    template_name = "sustainability/confirm_delete.html"

    def page_title(self):
        return f"Supprimer « {self.object} »"

    def form_valid(self, form):
        messages.success(self.request, f"« {self.object} » supprimé.")
        return super().form_valid(form)


class TargetList(AuthListView):
    model = ConservationTarget
    template_name = "sustainability/target_list.html"
    queryset = ConservationTarget.objects.select_related("site")


class TargetDetail(AuthDetailView):
    model = ConservationTarget
    template_name = "sustainability/target_detail.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        target = self.object
        measured = executive_metrics(target.site, target.period_start, target.period_end)["consumption_m3"]
        ctx["measured_m3"] = measured
        ctx["progress_pct"] = round(100 * (float(target.baseline_m3) - measured) / (float(target.baseline_m3) - float(target.target_m3)), 1) \
            if measured and target.baseline_m3 > target.target_m3 else None
        return ctx


class TargetCreate(AuthCreateView):
    model, form_class = ConservationTarget, ConservationTargetForm


class TargetUpdate(AuthUpdateView):
    model, form_class = ConservationTarget, ConservationTargetForm


class TargetDelete(AuthDeleteView):
    model = ConservationTarget


class ProjectList(AuthListView):
    model = SustainabilityProject
    template_name = "sustainability/project_list.html"
    queryset = SustainabilityProject.objects.select_related("site")


class ProjectDetail(AuthDetailView):
    model = SustainabilityProject
    template_name = "sustainability/project_detail.html"


class ProjectCreate(AuthCreateView):
    model, form_class = SustainabilityProject, SustainabilityProjectForm


class ProjectUpdate(AuthUpdateView):
    model, form_class = SustainabilityProject, SustainabilityProjectForm


class ProjectDelete(AuthDeleteView):
    model = SustainabilityProject


class BenefitList(AuthListView):
    model = MeasuredBenefit
    template_name = "sustainability/benefit_list.html"
    queryset = MeasuredBenefit.objects.select_related("project", "project__site")


class BenefitDetail(AuthDetailView):
    model = MeasuredBenefit
    template_name = "sustainability/benefit_detail.html"


class BenefitCreate(AuthCreateView):
    model, form_class = MeasuredBenefit, MeasuredBenefitForm

    def get_initial(self):
        project = self.request.GET.get("project")
        return {"project": int(project)} if project and project.isdigit() else {}


class BenefitUpdate(AuthUpdateView):
    model, form_class = MeasuredBenefit, MeasuredBenefitForm


class BenefitDelete(AuthDeleteView):
    model = MeasuredBenefit


@login_required
def dashboard(request):
    site_id = request.GET.get("site")
    site = get_object_or_404(Site, pk=site_id) if site_id and site_id.isdigit() else None
    return render(request, "sustainability/dashboard.html", {"metrics": executive_metrics(site), "site": site, "sites": Site.objects.all()})


@login_required
@permission_required("sustainability.add_optimizationrun", raise_exception=True)
def optimize(request):
    form = OptimizationRunForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        run = form.save(commit=False)
        projects = SustainabilityProject.objects.filter(status__in=["proposed", "approved", "in_progress"])
        if run.site:
            projects = projects.filter(site=run.site)
        result = optimize_projects(projects, run.budget_tnd)
        run.solver = result["solver"]
        run.recommendations = [{"id": p.pk, "name": p.name, "cost_tnd": str(p.budget_tnd), "savings_m3": str(p.expected_savings_m3)} for p in result["projects"]]
        run.total_cost_tnd, run.projected_savings_m3 = result["total_cost"], result["savings"]
        run.projected_annual_savings_tnd, run.payback_months = result["annual_savings"], result["payback"]
        run.created_by = request.user
        run.save()
        return redirect(run.get_absolute_url())
    return render(request, "sustainability/optimization_form.html", {
        "form": form, **MODULE, "page_title": "Optimiser le budget", "submit_label": "Lancer l'optimisation",
        "cancel_url": reverse_lazy("sustainability:project_list"),
        "recent_runs": OptimizationRun.objects.select_related("site")[:5],
        "page_intro": "Choisit, parmi les projets proposés, approuvés ou en cours, la combinaison qui économise le plus d'eau sans dépasser le budget.",
    })


class OptimizationDetail(AuthDetailView):
    model = OptimizationRun
    template_name = "sustainability/optimization_detail.html"


@login_required
@permission_required("sustainability.add_auditreport", raise_exception=True)
def audit_report(request):
    end = date.today()
    start = end - timedelta(days=90)
    error = None
    if request.method == "POST":
        try:
            start = date.fromisoformat(request.POST.get("period_start") or str(start))
            end = date.fromisoformat(request.POST.get("period_end") or str(end))
        except ValueError:
            error = "Dates invalides."
        if not error and end < start:
            error = "La fin de période doit être postérieure au début."
        if not error:
            site_id = request.POST.get("site") or None
            site = Site.objects.filter(pk=site_id).first() if site_id and str(site_id).isdigit() else None
            report = AuditReport.objects.create(site=site, period_start=start, period_end=end, generated_by=request.user,
                                                snapshot=executive_metrics(site, start, end))
            return redirect("sustainability:audit_pdf", pk=report.pk)
    return render(request, "sustainability/audit_form.html", {
        "period_start": start, "period_end": end, "sites": Site.objects.all(), "error": error, **MODULE,
    })


@login_required
def audit_list(request):
    return render(request, "sustainability/audit_list.html", {"reports": AuditReport.objects.select_related("site", "generated_by")})


@login_required
def audit_pdf(request, pk):
    report = get_object_or_404(AuditReport, pk=pk)
    try:
        content = render_audit_pdf(report)
    except PdfUnavailable as exc:
        messages.error(request, str(exc))
        return redirect("sustainability:audit_list")
    response = HttpResponse(content, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="aquamind-audit-{report.pk}.pdf"'
    return response
