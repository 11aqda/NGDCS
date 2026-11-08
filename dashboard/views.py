from datetime import date, timedelta

from django.contrib.auth.models import User
from django.db.models import Avg, Count, Max
from django.db.models.functions import TruncDate
from django.shortcuts import render

from accounts.models import ScoreRecord


def index(request):
    stats = ScoreRecord.objects.aggregate(  # 分数汇总，返回一个字典
        total=Count("id"),#求总对局数
        avg_score=Avg("score"),#求平均分数
        max_score=Max("score"),#求最高分
    )

    today = date.today()
    start_day = today - timedelta(days=6)
    trend_rows = (
        ScoreRecord.objects
        .filter(created_at__date__gte=start_day)  #最近 7 天
        .annotate(day=TruncDate("created_at"))  #按天分组
        .values("day")
        .annotate(
            count=Count("id"),
            avg_score=Avg("score"),
        )
        .order_by("day")
    )
    trend_map = {row["day"]: row for row in trend_rows}
    trend_days = []
    trend_counts = []
    trend_avg = []
    for offset in range(7):
        day = start_day + timedelta(days=offset)
        row = trend_map.get(day)
        trend_days.append(day.strftime("%m-%d"))
        trend_counts.append(row["count"] if row else 0)
        trend_avg.append(round(row["avg_score"], 1) if row else None)

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
    }
    return render(request, "dashboard/index.html", context)
