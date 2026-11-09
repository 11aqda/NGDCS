"""总路由：API + 管理员看板。"""

from django.contrib.auth import views as auth_views
from django.urls import include, path

urlpatterns = [
    path("api/", include("accounts.urls")),
    path("accounts/login/", auth_views.LoginView.as_view(template_name="registration/login.html"), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("dashboard/", include("dashboard.urls")),
]