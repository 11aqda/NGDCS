"""`/api/v2/` 的路由：只挂一个只读资源。"""

from __future__ import annotations

from rest_framework.routers import DefaultRouter

from accounts.api import ScoreRecordViewSet

router = DefaultRouter()
router.register("runs", ScoreRecordViewSet, basename="run")

urlpatterns = router.urls
