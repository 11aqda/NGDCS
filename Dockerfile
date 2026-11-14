# NGDC S·portfolio —— Django 看板/API 镜像
#
# 只装 Web 层依赖（requirements-web.txt）；游戏客户端 / 实验工具不进镜像。
# 构建：docker compose build
# 运行：docker compose up -d
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# curl：给 compose healthcheck / 手工探活用；装完清缓存
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-web.txt .
RUN pip install --no-cache-dir -r requirements-web.txt

COPY . .

RUN chmod +x deploy/entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/deploy/entrypoint.sh"]
