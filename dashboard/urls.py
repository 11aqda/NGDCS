from django.urls import path

from . import views

urlpatterns = [
    path("", views.index, name="dashboard"),
    path("matches/", views.matches, name="matches"),
]