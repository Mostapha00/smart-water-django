# tracker/urls.py
from django.urls import path
from . import views

urlpatterns = [
path('', views. home, name='home'),
path('entries/', views. entry_list, name='entry_list'),
path('entries/new/', views. entry_create, name='entry_create'),
path('entries/<int:id>/', views.entry_detail, name='entry_detail'),
path('entries/<int:id>/edit/', views.entry_edit, name='entry_edit'),
path('entries/<int: id>/delete/', views.entry_delete, name='entry_delete'),
path('tags/', views. tag_list, name='tag_list'),
path('tags/<slug:slug>/', views. tag_detail, name='tag_detail'),
path('categories/', views. category_list, name='category_list'),
path('stats/', views. stats, name='stats'),
]