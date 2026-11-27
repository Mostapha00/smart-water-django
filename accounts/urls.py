from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path("connexion/", views.AquaLoginView.as_view(), name="login"),
    path("inscription/", views.SignUpView.as_view(), name="signup"),
    path("deconnexion/", auth_views.LogoutView.as_view(), name="logout"),
]
