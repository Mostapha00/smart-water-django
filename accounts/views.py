from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.views.generic import CreateView

from .forms import SignUpForm
from .models import AuditManager, NetworkTechnician


class SignUpView(CreateView):
    """Crée un compte (sans aucune permission) puis connecte l'utilisateur."""

    form_class = SignUpForm
    template_name = "registration/signup.html"
    success_url = reverse_lazy(settings.LOGIN_REDIRECT_URL)

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect(settings.LOGIN_REDIRECT_URL)
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        response = super().form_valid(form)
        login(self.request, self.object, backend="django.contrib.auth.backends.ModelBackend")
        messages.success(
            self.request,
            f"Bienvenue {self.object.first_name} ! Votre compte est créé en lecture seule : "
            "demandez à un administrateur de vous attribuer des droits de modification.",
        )
        return response


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
