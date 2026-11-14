"""DRF 只读接口：`GET /api/v2/runs/`（对局记录）。

## 为什么单开 v2，而不是改现有接口

现有 `/api/auth/*`、`/api/leaderboard` 是纯 Django `JsonResponse`（D-031），
**一行不动**。这里加一个只读资源，专门演示 DRF 的四件套：

`ModelSerializer` → `ReadOnlyModelViewSet` → `DefaultRouter` → 分页/过滤/权限

## 权限

`IsAdminUser` + `SessionAuthentication`：

- 管理员在 `/dashboard/` 登录后，浏览器直接能看（同一个 session）
- 匿名请求由 DRF 返回 **403**（SessionAuthentication 不返回 WWW-Authenticate，
  所以 DRF 不会给 401）—— 验收时两种都接受
- 只读：`ReadOnlyModelViewSet` 只有 list/retrieve，POST/PUT/PATCH/DELETE 一律 405

## 过滤

用 DRF 内置的 `SearchFilter` + `OrderingFilter`，**不装 django-filter**：

```text
/api/v2/runs/?search=sakura
/api/v2/runs/?ordering=-score
/api/v2/runs/?page=2&page_size=50
```
"""

from __future__ import annotations

from rest_framework import filters, serializers, viewsets
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAdminUser

from accounts.models import ScoreRecord


class ScoreRecordSerializer(serializers.ModelSerializer):
    """对局记录（只读）。

    `username` 拉平出来：前端不需要再按 user id 查一次（也避免嵌套序列化器
    把 `/api/v1/users/<id>/` 这种并不存在的资源编出来）。
    """

    username = serializers.CharField(source="user.username", read_only=True)

    class Meta:
        model = ScoreRecord
        fields = ["id", "username", "score", "level", "kills", "created_at"]
        read_only_fields = fields


class RunPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class ScoreRecordViewSet(viewsets.ReadOnlyModelViewSet):
    """`/api/v2/runs/` 与 `/api/v2/runs/<id>/`。

    `select_related("user")`：列表页每行都要 `user.username`，不 join 就是 N+1。
    """

    queryset = ScoreRecord.objects.select_related("user").all()
    serializer_class = ScoreRecordSerializer
    permission_classes = [IsAdminUser]
    pagination_class = RunPagination
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["user__username"]
    ordering_fields = ["score", "level", "kills", "created_at"]
    ordering = ["-score", "-created_at"]
