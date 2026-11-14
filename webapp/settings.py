"""Django 配置：只做**账号 + 排行榜**这一层 HTTP 接口。

## 为什么是"纯 Django"而不是 DRF

`04-API接口设计.md` 原定用 Django REST Framework，实际改成纯 Django。理由：

1. **只有 3 个接口**（注册 / 登录 / 排行榜），没有一个需要序列化器的嵌套能力
2. 环境受限 —— DRF 装不上时整层就卡住，而 `JsonResponse` 是零依赖
3. 手写视图反而更容易看清"每个接口到底做了什么"

取舍记在 D-031。

## 为什么 INSTALLED_APPS / MIDDLEWARE 这么短

这是**纯 JSON API**，不出网页：
- 不需要 `admin`（要模板、静态文件、messages 一整串）
- 不需要 `sessions` / `messages`（用自建 token 表认证）
- **必须去掉 `CsrfViewMiddleware`** —— 客户端不是浏览器，拿不到 CSRF token，
  留着会把所有 POST 变成 403

## 数据库

MySQL 8.0.41 的库 `myproject`，用 **PyMySQL** 驱动（D-001：Windows 上免编译）。
密码是**本地开发用**，上线前必须改（仓库为私有，见 PROGRESS §2.2）。
"""

import os
from pathlib import Path

import pymysql
from django.core.exceptions import ImproperlyConfigured

# Django 连接的驱动名固定是 MySQLdb，PyMySQL 通过这行冒充它（D-001）
pymysql.install_as_MySQLdb()

BASE_DIR = Path(__file__).resolve().parent.parent

# 本地开发从 .env 读（.env 在 .gitignore 里，不进仓库）；容器里由 compose 注入环境变量。
try:  # python-dotenv 是可选依赖：没有它也不影响容器/显式设置环境变量的用法
    from dotenv import load_dotenv

    load_dotenv(BASE_DIR / ".env")
except ImportError:  # pragma: no cover
    pass

DEBUG = os.environ.get("NGDCS_DEBUG", "1") == "1"

# **没有默认值**：密钥只能从环境变量 / .env 来，仓库里不留可用密钥。
SECRET_KEY = os.environ.get("NGDCS_SECRET_KEY", "")
if not SECRET_KEY:
    raise ImproperlyConfigured(
        "缺少 NGDCS_SECRET_KEY。请复制 .env.example 为 .env 并填一个随机串：\n"
        '  python -c "import secrets; print(secrets.token_urlsafe(50))"'
    )

ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get(
        "NGDCS_ALLOWED_HOSTS", "127.0.0.1,localhost"
    ).split(",")
    if host.strip()
]

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.auth",  # 直接用内置 auth_user，不自己造用户表
    "django.contrib.staticfiles",  # nginx 托管 /static/（DRF 浏览页、登录页）
    "rest_framework",  # /api/v2/runs/ 只读接口（DRF）
    "accounts",
    "dashboard",
]

STATIC_URL = "/static/"
# collectstatic 的落点；compose 里 nginx 直接读这个目录
STATIC_ROOT = BASE_DIR / "staticfiles"

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
]

ROOT_URLCONF = "webapp.urls"
WSGI_APPLICATION = "webapp.wsgi.application"

LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/dashboard/"
LOGOUT_REDIRECT_URL = "/accounts/login/"

# DRF 默认口径：以后新增 ViewSet 忘写权限时，默认就是"仅管理员"，而不是裸奔。
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAdminUser",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_FILTER_BACKENDS": [
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
}

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
            ]
        },
    },
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": os.environ.get("NGDCS_DB_NAME", "myproject"),
        "USER": os.environ.get("NGDCS_DB_USER", "django_user"),
        "PASSWORD": os.environ.get("NGDCS_DB_PASSWORD", ""),
        "HOST": os.environ.get("NGDCS_DB_HOST", "127.0.0.1"),
        "PORT": os.environ.get("NGDCS_DB_PORT", "3306"),
        "OPTIONS": {"charset": "utf8mb4"},
    }
}

# 排行榜缓存（ZSET）+ 实时指标。Django 不缓存别的东西，只用它读排行榜
REDIS = {
    "host": os.environ.get("NGDCS_REDIS_HOST", "127.0.0.1"),
    "port": int(os.environ.get("NGDCS_REDIS_PORT", "6379")),
    "db": 0,
}
LEADERBOARD_KEY = "lb:best_score"

# Web 读游戏端每秒写出的指标。
# 默认读本工作区 data/；论文工作区跑服务端时用环境变量指过去（14 §11.10）。
METRICS_CSV = Path(
    os.environ.get("NGDCS_METRICS_CSV") or BASE_DIR / "data" / "server_metrics.csv"
)

# 实时指标（服务端 --live-metrics 写 Redis Hash，TTL 10 秒）。
# 看板优先读它；读不到 / 过期 / 连不上就回退到 CSV 最后一行。
LIVE_METRICS_KEY = "ngdcs:metrics:live"
LIVE_METRICS_TTL = 10

AUTH_PASSWORD_VALIDATORS = []
LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = False
USE_TZ = False
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "WARNING"},
}