from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render

from .models import WaterMeter


@login_required
def meter_list(request):
    meters = WaterMeter.objects.select_related("zone", "zone__site").prefetch_related("readings")
    return render(request, "consumption/meter_list.html", {"meters": meters})


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
