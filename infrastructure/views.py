import json
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, ProtectedError, Q
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from .forms import CloseWorkForm, MaintenanceWorkForm, SiteForm, WaterPipeForm, WaterPumpForm, WaterZoneForm
from .models import MaintenanceWork, Site, WaterPipe, WaterPump, WaterZone
from .services.maquette import build_payload


class FormTitleMixin:
    """Fournit un titre et un lien d'annulation au gabarit générique form.html."""

    title = ""
    cancel_url = reverse_lazy("infrastructure:site_list")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = self.title or (f"Modifier {self.object}" if getattr(self, "object", None) else "Ajouter")
        ctx["cancel_url"] = self.get_cancel_url()
        return ctx

    def get_cancel_url(self):
        obj = getattr(self, "object", None)
        return obj.get_absolute_url() if obj is not None and obj.pk else self.cancel_url

    def form_valid(self, form):
        messages.success(self.request, "Enregistré.")
        return super().form_valid(form)


class SafeDeleteMixin:
    """Affiche un message clair quand la suppression est bloquée par des objets liés."""

    template_name = "infrastructure/confirm_delete.html"

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        try:
            self.object.delete()
        except ProtectedError:
            messages.error(request, f"Impossible de supprimer {self.object} : des éléments y sont encore rattachés.")
            return redirect(self.object.get_absolute_url())
        messages.success(request, "Supprimé.")
        return redirect(self.get_success_url())


# ----------------------------------------------------------------- Sites

class SiteListView(LoginRequiredMixin, ListView):
    model = Site
    template_name = "infrastructure/site_list.html"

    def get_queryset(self):
        return Site.objects.annotate(
            zone_count=Count("zones", distinct=True),
            pipe_count=Count("zones__waterpipes", distinct=True),
            pump_count=Count("zones__waterpumps", distinct=True),
        )


class SiteDetailView(LoginRequiredMixin, DetailView):
    model = Site
    template_name = "infrastructure/site_detail.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        site = self.object
        zones = site.zones.prefetch_related("waterpipes", "waterpumps")
        equipment = site.equipment()
        ctx.update({
            "zones": zones,
            "equipment_count": len(equipment),
            "high_risk": sorted([e for e in equipment if e.failure_risk_30d is not None and e.failure_risk_30d >= Decimal("0.6")],
                                key=lambda e: e.failure_risk_30d, reverse=True),
            "problems": [e for e in equipment if e.status in ("a_surveiller", "en_panne")],
            "open_works": MaintenanceWork.objects.filter(Q(pipe__zone__site=site) | Q(pump__zone__site=site), completed_at__isnull=True)
                          .select_related("pipe", "pump", "technician"),
        })
        try:
            site.validate_structure()
            ctx["structure_error"] = None
        except ValidationError as e:
            ctx["structure_error"] = e.messages[0]
        return ctx


class SiteCreateView(PermissionRequiredMixin, FormTitleMixin, CreateView):
    permission_required = "infrastructure.add_site"
    model = Site
    form_class = SiteForm
    template_name = "infrastructure/form.html"
    title = "Nouveau site"


class SiteUpdateView(PermissionRequiredMixin, FormTitleMixin, UpdateView):
    permission_required = "infrastructure.change_site"
    model = Site
    form_class = SiteForm
    template_name = "infrastructure/form.html"


class SiteDeleteView(PermissionRequiredMixin, SafeDeleteMixin, DeleteView):
    permission_required = "infrastructure.delete_site"
    model = Site
    success_url = reverse_lazy("infrastructure:site_list")


# ----------------------------------------------------------------- Zones

class ZoneCreateView(PermissionRequiredMixin, FormTitleMixin, CreateView):
    permission_required = "infrastructure.add_waterzone"
    model = WaterZone
    form_class = WaterZoneForm
    template_name = "infrastructure/form.html"
    title = "Nouvelle zone"

    def get_initial(self):
        return {"site": self.request.GET.get("site")}


class ZoneUpdateView(PermissionRequiredMixin, FormTitleMixin, UpdateView):
    permission_required = "infrastructure.change_waterzone"
    model = WaterZone
    form_class = WaterZoneForm
    template_name = "infrastructure/form.html"


class ZoneDeleteView(PermissionRequiredMixin, SafeDeleteMixin, DeleteView):
    permission_required = "infrastructure.delete_waterzone"
    model = WaterZone

    def get_success_url(self):
        return reverse("infrastructure:site_detail", args=[self.object.site_id])


@require_POST
@permission_required("infrastructure.change_waterzone", raise_exception=True)
def zone_position(request, pk):
    """Enregistre la position 3D d'une zone (appelé par la maquette en mode édition)."""
    zone = get_object_or_404(WaterZone, pk=pk)
    try:
        data = json.loads(request.body)
        zone.pos_x = Decimal(str(data["pos_x"])).quantize(Decimal("0.01"))
        zone.pos_y = Decimal(str(data["pos_y"])).quantize(Decimal("0.01"))
    except (ValueError, KeyError, TypeError, InvalidOperation):
        return HttpResponseBadRequest("pos_x et pos_y numériques attendus.")
    if abs(zone.pos_x) > 500 or abs(zone.pos_y) > 500:
        return HttpResponseBadRequest("Position hors limites.")
    zone.save(update_fields=["pos_x", "pos_y"])
    return JsonResponse({"id": zone.pk, "pos_x": float(zone.pos_x), "pos_y": float(zone.pos_y)})


# ----------------------------------------------------------------- Équipements

class EquipmentDetailView(LoginRequiredMixin, DetailView):
    template_name = "infrastructure/equipment_detail.html"
    context_object_name = "equipment"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["works"] = self.object.maintenance_works.select_related("technician")
        ctx["replacement_cost"] = self.object.estimate_replacement_cost()
        return ctx


class PipeDetailView(EquipmentDetailView):
    model = WaterPipe


class PumpDetailView(EquipmentDetailView):
    model = WaterPump


class EquipmentCreateMixin(PermissionRequiredMixin, FormTitleMixin):
    template_name = "infrastructure/form.html"

    def get_initial(self):
        return {"zone": self.request.GET.get("zone")}


class PipeCreateView(EquipmentCreateMixin, CreateView):
    permission_required = "infrastructure.add_waterpipe"
    model = WaterPipe
    form_class = WaterPipeForm
    title = "Nouvelle canalisation"


class PumpCreateView(EquipmentCreateMixin, CreateView):
    permission_required = "infrastructure.add_waterpump"
    model = WaterPump
    form_class = WaterPumpForm
    title = "Nouvelle pompe"


class PipeUpdateView(PermissionRequiredMixin, FormTitleMixin, UpdateView):
    permission_required = "infrastructure.change_waterpipe"
    model = WaterPipe
    form_class = WaterPipeForm
    template_name = "infrastructure/form.html"


class PumpUpdateView(PermissionRequiredMixin, FormTitleMixin, UpdateView):
    permission_required = "infrastructure.change_waterpump"
    model = WaterPump
    form_class = WaterPumpForm
    template_name = "infrastructure/form.html"


class EquipmentDeleteMixin(PermissionRequiredMixin, SafeDeleteMixin):
    def get_success_url(self):
        return reverse("infrastructure:site_detail", args=[self.object.zone.site_id])


class PipeDeleteView(EquipmentDeleteMixin, DeleteView):
    permission_required = "infrastructure.delete_waterpipe"
    model = WaterPipe


class PumpDeleteView(EquipmentDeleteMixin, DeleteView):
    permission_required = "infrastructure.delete_waterpump"
    model = WaterPump


@require_POST
@login_required
def equipment_predict(request, kind, pk):
    model = {"pipe": WaterPipe, "pump": WaterPump}.get(kind)
    if model is None:
        return HttpResponseBadRequest("Type d'équipement inconnu.")
    if not request.user.has_perm(f"infrastructure.change_{model._meta.model_name}"):
        raise PermissionDenied
    eq = get_object_or_404(model, pk=pk)
    risk = eq.predict_failure_30d()
    messages.success(request, f"Risque de panne à 30 jours recalculé : {risk * 100:.0f} % ({eq.model_version}).")
    return redirect(eq.get_absolute_url())


# ----------------------------------------------------------------- Maintenance

class WorkListView(LoginRequiredMixin, ListView):
    model = MaintenanceWork
    template_name = "infrastructure/work_list.html"
    paginate_by = 30

    def get_queryset(self):
        qs = MaintenanceWork.objects.select_related("pipe__zone__site", "pump__zone__site", "technician")
        state = self.request.GET.get("etat")
        if state == "ouvertes":
            qs = qs.filter(completed_at__isnull=True)
        elif state == "terminees":
            qs = qs.filter(completed_at__isnull=False)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["state"] = self.request.GET.get("etat", "")
        return ctx


class WorkDetailView(LoginRequiredMixin, DetailView):
    model = MaintenanceWork
    template_name = "infrastructure/work_detail.html"
    context_object_name = "work"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["close_form"] = CloseWorkForm(initial={"cost_tnd": self.object.cost_tnd, "work_summary": self.object.work_summary})
        return ctx


class WorkCreateView(PermissionRequiredMixin, FormTitleMixin, CreateView):
    permission_required = "infrastructure.add_maintenancework"
    model = MaintenanceWork
    form_class = MaintenanceWorkForm
    template_name = "infrastructure/form.html"
    title = "Planifier une maintenance"
    cancel_url = reverse_lazy("infrastructure:work_list")

    def get_initial(self):
        """Pré-remplit la cible depuis ?pipe=<id> ou ?pump=<id> (bouton de la maquette 3D)."""
        initial = {"maintenance_type": self.request.GET.get("type", "corrective")}
        for key in ("pipe", "pump"):
            value = self.request.GET.get(key)
            if value and value.isdigit():
                initial[key] = int(value)
        return initial


class WorkUpdateView(PermissionRequiredMixin, FormTitleMixin, UpdateView):
    permission_required = "infrastructure.change_maintenancework"
    model = MaintenanceWork
    form_class = MaintenanceWorkForm
    template_name = "infrastructure/form.html"


@require_POST
@permission_required("infrastructure.change_maintenancework", raise_exception=True)
def work_close(request, pk):
    work = get_object_or_404(MaintenanceWork, pk=pk)
    form = CloseWorkForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Formulaire invalide.")
        return redirect(work.get_absolute_url())
    try:
        work.close_work(cost_tnd=form.cleaned_data["cost_tnd"], summary=form.cleaned_data["work_summary"])
    except ValidationError as e:
        messages.error(request, e.messages[0])
    else:
        messages.success(request, f"{work.reference} clôturée.")
    return redirect(work.get_absolute_url())


# ----------------------------------------------------------------- Maquette 3D

@login_required
def site_maquette(request, pk):
    site = get_object_or_404(Site, pk=pk)
    return render(request, "infrastructure/maquette.html", {"site": site})


@login_required
def site_maquette_json(request, pk):
    site = get_object_or_404(Site, pk=pk)
    return JsonResponse(build_payload(site, request.user), json_dumps_params={"ensure_ascii": False})
