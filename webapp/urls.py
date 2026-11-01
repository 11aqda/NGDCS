"""总路由：只挂 API，不出网页（`admin` 也没开 —— 见 settings 的说明）。"""

from django.urls import include, path

urlpatterns = [
    path("api/", include("accounts.urls")),
]