"""账号 / 排行榜的 URL 路由 —— 只有 3 个接口（`04 §2.2`）。"""

from django.urls import path

from accounts import views

urlpatterns = [
    path("auth/register", views.register, name="register"),
    path("auth/login", views.login, name="login"),
    path("leaderboard", views.leaderboard, name="leaderboard"),
]