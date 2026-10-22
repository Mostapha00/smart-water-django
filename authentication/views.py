# authentication/views.py
from django.http import HttpResponse

def signup(request):
    return HttpResponse("Sign-up form - coming soon")

def login_view(request):
    return HttpResponse("Login form - coming soon")

def logout_view(request):
    return HttpResponse("You have been logged out")

def profile(request):
    return HttpResponse("Your profile page - coming soon")