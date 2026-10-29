import json
from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from .forms import ConservationTargetForm, MeasuredBenefitForm, OptimizationRunForm, SustainabilityProjectForm
from .models import AuditReport, ConservationTarget, MeasuredBenefit, OptimizationRun, SustainabilityProject
from .services.dashboard import executive_metrics
from .services.optimization import optimize_projects
from .services.pdf import render_audit_pdf


class LoginRequiredMixin:
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            from django.contrib.auth.views import redirect_to_login
            return redirect_to_login(request.get_full_path())
        return super().dispatch(request, *args, **kwargs)


class AuthListView(LoginRequiredMixin, ListView):
    template_name = "sustainability/list.html"
    context_object_name = "objects"


class AuthDetailView(LoginRequiredMixin, DetailView):
    template_name = "sustainability/detail.html"


class AuthCreateView(LoginRequiredMixin, CreateView):
    template_name = "sustainability/form.html"

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Enregistrement créé.")
        return response


class AuthUpdateView(LoginRequiredMixin, UpdateView):
    template_name = "sustainability/form.html"


class AuthDeleteView(LoginRequiredMixin, DeleteView):
    template_name = "sustainability/confirm_delete.html"
    success_url = reverse_lazy("sustainability:dashboard")


class TargetList(AuthListView):
    model = ConservationTarget
    template_name = "sustainability/target_list.html"


class TargetDetail(AuthDetailView):
    model = ConservationTarget


class TargetCreate(AuthCreateView):
    model, form_class, success_url = ConservationTarget, ConservationTargetForm, reverse_lazy("sustainability:target_list")


class TargetUpdate(AuthUpdateView):
    model, form_class, success_url = ConservationTarget, ConservationTargetForm, reverse_lazy("sustainability:target_list")


class TargetDelete(AuthDeleteView):
    model = ConservationTarget


class ProjectList(AuthListView):
    model = SustainabilityProject
    template_name = "sustainability/project_list.html"


class ProjectDetail(AuthDetailView):
    model = SustainabilityProject


class ProjectCreate(AuthCreateView):
    model, form_class, success_url = SustainabilityProject, SustainabilityProjectForm, reverse_lazy("sustainability:project_list")


class ProjectUpdate(AuthUpdateView):
    model, form_class, success_url = SustainabilityProject, SustainabilityProjectForm, reverse_lazy("sustainability:project_list")


class ProjectDelete(AuthDeleteView):
    model = SustainabilityProject


class BenefitList(AuthListView):
    model = MeasuredBenefit
    template_name = "sustainability/benefit_list.html"


class BenefitDetail(AuthDetailView):
    model = MeasuredBenefit


class BenefitCreate(AuthCreateView):
    model, form_class, success_url = MeasuredBenefit, MeasuredBenefitForm, reverse_lazy("sustainability:benefit_list")


class BenefitUpdate(AuthUpdateView):
    model, form_class, success_url = MeasuredBenefit, MeasuredBenefitForm, reverse_lazy("sustainability:benefit_list")


class BenefitDelete(AuthDeleteView):
    model = MeasuredBenefit


@login_required
def dashboard(request):
    site_id = request.GET.get("site")
    site = None
    if site_id:
        from infrastructure.models import Site
        site = get_object_or_404(Site, pk=site_id)
    return render(request, "sustainability/dashboard.html", {"metrics": executive_metrics(site), "site": site})


@login_required
def optimize(request):
    if request.method == "POST":
        form = OptimizationRunForm(request.POST)
        if form.is_valid():
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
    else:
        form = OptimizationRunForm()
    return render(request, "sustainability/optimization_form.html", {"form": form})


class OptimizationDetail(AuthDetailView):
    model = OptimizationRun
    template_name = "sustainability/optimization_detail.html"


@login_required
def audit_report(request):
    end = date.today()
    start = end - timedelta(days=90)
    if request.method == "POST":
        start = date.fromisoformat(request.POST.get("period_start", str(start)))
        end = date.fromisoformat(request.POST.get("period_end", str(end)))
        site_id = request.POST.get("site") or None
        from infrastructure.models import Site
        site = Site.objects.filter(pk=site_id).first() if site_id else None
        report = AuditReport.objects.create(site=site, period_start=start, period_end=end, generated_by=request.user, snapshot=executive_metrics(site))
        return redirect("sustainability:audit_pdf", pk=report.pk)
    return render(request, "sustainability/audit_form.html", {"period_start": start, "period_end": end})


@login_required
def audit_list(request):
    return render(request, "sustainability/audit_list.html", {"reports": AuditReport.objects.select_related("site", "generated_by")})


@login_required
def audit_pdf(request, pk):
    report = get_object_or_404(AuditReport, pk=pk)
    response = HttpResponse(render_audit_pdf(report), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="aquamind-audit-{report.pk}.pdf"'
    return response
