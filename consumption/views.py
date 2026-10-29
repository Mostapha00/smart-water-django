from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import CreateView
from django.urls import reverse_lazy
from django.contrib.auth.mixins import LoginRequiredMixin

from .forms import MeterReadingForm, TariffBandForm, WaterBillForm, WaterMeterForm
from .models import MeterReading, TariffBand, WaterBill, WaterMeter


@login_required
def meter_list(request):
    meters = WaterMeter.objects.select_related("zone", "zone__site").prefetch_related("readings")
    return render(request, "consumption/meter_list.html", {"meters": meters})


@login_required
def dashboard(request):
    meters = WaterMeter.objects.count()
    readings = sum(m.readings.count() for m in WaterMeter.objects.prefetch_related("readings"))
    bills = WaterBill.objects.count()
    return render(request, "consumption/dashboard.html", {"meter_count": meters, "reading_count": readings, "bill_count": bills, "recent_bills": WaterBill.objects.select_related("meter").order_by("-period_end")[:5]})


class MeterCreateView(LoginRequiredMixin, CreateView):
    model = WaterMeter
    form_class = WaterMeterForm
    template_name = "consumption/form.html"
    success_url = reverse_lazy("consumption:meter_list")


meter_create = MeterCreateView.as_view()


class ReadingCreateView(LoginRequiredMixin, CreateView):
    model = MeterReading
    form_class = MeterReadingForm
    template_name = "consumption/form.html"
    success_url = reverse_lazy("consumption:meter_list")

    def form_valid(self, form):
        response = super().form_valid(form)
        self.object.meter.forecast_consumption()
        return response


reading_create = ReadingCreateView.as_view()


class TariffCreateView(LoginRequiredMixin, CreateView):
    model = TariffBand
    form_class = TariffBandForm
    template_name = "consumption/form.html"
    success_url = reverse_lazy("consumption:tariff_list")


tariff_create = TariffCreateView.as_view()


class BillCreateView(LoginRequiredMixin, CreateView):
    model = WaterBill
    form_class = WaterBillForm
    template_name = "consumption/form.html"
    success_url = reverse_lazy("consumption:bill_list")

    def form_valid(self, form):
        response = super().form_valid(form)
        self.object.calculate_amounts()
        return response


bill_create = BillCreateView.as_view()


@login_required
def tariff_list(request):
    return render(request, "consumption/tariff_list.html", {"tariffs": TariffBand.objects.all()})


@login_required
def bill_list(request):
    return render(request, "consumption/bill_list.html", {"bills": WaterBill.objects.select_related("meter", "sonede_band", "onas_band")})


@login_required
def meter_detail(request, pk):
    meter = get_object_or_404(WaterMeter.objects.select_related("zone", "zone__site"), pk=pk)
    return render(request, "consumption/meter_detail.html", {"meter": meter, "readings": meter.readings.all()})


@login_required
def meter_import(request, pk):
    meter = get_object_or_404(WaterMeter, pk=pk)
    if request.method != "POST" or "file" not in request.FILES:
        return HttpResponseBadRequest("Un fichier CSV est requis.")
    try:
        imported = meter.import_csv_readings(request.FILES["file"])
    except ValidationError as exc:
        return HttpResponseBadRequest("; ".join(exc.messages))
    meter.forecast_consumption()
    messages.success(request, f"{len(imported)} relevé(s) importé(s).")
    return redirect("consumption:meter_detail", pk=meter.pk)
