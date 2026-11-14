"""总路由：API + 管理员看板。

`/api/v2/` 是 DRF 的只读接口（`accounts/api_urls.py`），与现有 `/api/`
（纯 Django JsonResponse，D-031）并存，互不影响。
"""

from django.contrib.auth import views as auth_views
from django.urls import include, path

urlpatterns = [
    # DRF 只读接口：/api/v2/runs/、/api/v2/runs/<id>/
    path("api/v2/", include("accounts.api_urls")),
    # 现有接口：/api/auth/*、/api/leaderboard（不动）
    path("api/", include("accounts.urls")),
    path("accounts/login/", auth_views.LoginView.as_view(template_name="registration/login.html"), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("dashboard/", include("dashboard.urls")),
]
