import csv
from datetime import date, datetime, timedelta

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db.models import Avg, Count, Max
from django.db.models.functions import TruncDate
from django.http import HttpResponseForbidden
from django.shortcuts import render

from accounts.models import ScoreRecord


def _latest_metrics():
    path = settings.METRICS_CSV
    if not path.exists():
        return None

    last = None
    with path.open(newline="", encoding="utf-8") as fp:
        for last in csv.DictReader(fp):
            pass
    if not last:
        return None

    try:
        updated_at = datetime.fromisoformat(last["timestamp"])
        age = max(0, int((datetime.now() - updated_at).total_seconds()))
        return {
            "online": int(float(last.get("client_count") or 0)),
            "tick_p95": float(last.get("tick_ms_p95") or 0),
            "bandwidth_kbps": float(last.get("bytes_out") or 0) / 1024,
            "snapshot_bytes": int(float(last.get("snapshot_bytes") or 0)),
            "cpu_percent": float(last.get("cpu_percent") or 0),
            "updated_at": last.get("timestamp", ""),
            "age": age,
            "live": age <= 5,
        }
    except (KeyError, ValueError):
        return None


@login_required
def index(request):
    if not request.user.is_staff:  # 只给管理员看
        return HttpResponseForbidden("需要管理员权限")
    stats = ScoreRecord.objects.aggregate(  # 分数汇总，返回一个字典
        total=Count("id"),#求总对局数
        avg_score=Avg("score"),#求平均分数
        max_score=Max("score"),#求最高分
    )

    today = date.today()
    start_day = today - timedelta(days=6)  # 算出6天前，刚好包含今天一共7天
    trend_rows = (
        ScoreRecord.objects
        .filter(created_at__date__gte=start_day)  #最近 7 天
        .annotate(day=TruncDate("created_at"))  #TruncDate具体时间截断成年月日
        .values("day")
        .annotate(
            count=Count("id"),  #局数
            avg_score=Avg("score"),  #求每天的平均分
        )
        .order_by("day")  #按日期排序
    )
    trend_map = {row["day"]: row for row in trend_rows}  #日期为key，整行统计为value
    trend_days = []
    trend_counts = []
    trend_avg = []
    for offset in range(7):
        day = start_day + timedelta(days=offset) #
        row = trend_map.get(day)  #验证有没有数据
        trend_days.append(day.strftime("%m-%d"))  #把日期对象变成 月—日 这种短格式，塞进列表里
        trend_counts.append(row["count"] if row else 0)  #有则塞，无则返0
        trend_avg.append(round(row["avg_score"], 1) if row else None)  #最终平均分保留一位小数，无则返None

    top_scores = list(
        ScoreRecord.objects.values("user__username")  #按用户名分组
        .annotate(best_score=Max("score"),games=Count("id"),)  #求每个玩家最高分和对局总数
        .order_by("-best_score")[:10]) #按分数倒序求前十名
    top_scores = [       #数据清洗、重组
        {
            "username": row["user__username"],
            "best_score": row["best_score"],
            "games": row["games"],
        }
        for row in top_scores   #拿出洗干净的数据
    ]
    chart_names = [row["username"] for row in top_scores]  #取出全部玩家用户名
    chart_scores = [row["best_score"] for row in top_scores]   #取出全部玩家最高分数

    context = {
        "user_count": User.objects.count(),   #总注册人数
        "stats": stats,  #第一步的全局统计
        "top_scores": top_scores,   #前十名玩家与分数
        "chart_names": chart_names,   #玩家名制作统计表x轴
        "chart_scores": chart_scores,   #玩家分数制作统计表y轴
        "trend_days": trend_days,   #最近 7 天日期
        "trend_counts": trend_counts,   #每天记录数
        "trend_avg": trend_avg,   #每天平均分
        "live_metrics": _latest_metrics(),   #服务端最近 1 秒指标
    }
    return render(request, "dashboard/index.html", context)


@login_required
def matches(request):
    if not request.user.is_staff:  # 只给管理员看
        return HttpResponseForbidden("需要管理员权限")

    keyword = request.GET.get("q", "").strip()
    records = ScoreRecord.objects.select_related("user").order_by("-created_at")  # 避免 N+1
    if keyword:
        records = records.filter(user__username__icontains=keyword)

    page_obj = Paginator(records, 20).get_page(request.GET.get("page"))  # 每页 20 条

    context = {
        "page_obj": page_obj,
        "keyword": keyword,
    }
    return render(request, "dashboard/matches.html", context)
