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

from pathlib import Path

import pymysql

# Django 连接的驱动名固定是 MySQLdb，PyMySQL 通过这行冒充它（D-001）
pymysql.install_as_MySQLdb()

BASE_DIR = Path(__file__).resolve().parent.parent

# ⚠️ 本地开发用。生产环境必须从环境变量注入并轮换
SECRET_KEY = "dev-only-ngdcs-secret-key-not-for-production"
DEBUG = True
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",  # 直接用内置 auth_user，不自己造用户表
    "accounts",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "webapp.urls"
WSGI_APPLICATION = "webapp.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": []},
    },
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": "myproject",
        "USER": "django_user",
        "PASSWORD": "123456",
        "HOST": "127.0.0.1",
        "PORT": "3306",
        "OPTIONS": {"charset": "utf8mb4"},
    }
}

# 排行榜缓存（ZSET）。Django 不缓存别的东西，只用它读写排行榜
REDIS = {"host": "127.0.0.1", "port": 6379, "db": 0}
LEADERBOARD_KEY = "lb:best_score"

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