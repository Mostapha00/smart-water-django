# tracker/views.py
from django.http import HttpResponse

def home(request) :
    return HttpResponse("MoodTracker home page")

def entry_list(request):
    return HttpResponse("Entries list - coming soon")

def entry_create(request) :
    return HttpResponse("Form to create a new mood entry - coming soon")

def entry_detail(request, id):
    return HttpResponse(f"Detail of entry #{id}")

def entry_edit(request, id):
    return HttpResponse(f"Edit form for entry #{id}")

def entry_delete(request, id):
    return HttpResponse(f"Confirm deletion of entry #{id}")

def tag_list(request):
    return HttpResponse("List of all tags")

def tag_detail(request, slug):
    return HttpResponse(f"Entries tagged '{slug} '")

def category_list(request):
    return HttpResponse("List of mood categories")

def stats(request) :
    return HttpResponse("Mood statistics - coming soon")