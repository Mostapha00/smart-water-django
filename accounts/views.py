from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .models import AuditManager, NetworkTechnician


@login_required
def overview(request):
    return render(
        request,
        "accounts/overview.html",
        {
            "technicians": NetworkTechnician.objects.filter(active=True),
            "managers": AuditManager.objects.filter(active=True),
        },
    )
