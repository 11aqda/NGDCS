#!/bin/sh
# 容器入口：等依赖 → 迁移 → 收静态文件 → gunicorn
set -e

wait_for() {
    host="$1"
    port="$2"
    name="$3"
    python - "$host" "$port" "$name" <<'PY'
import socket
import sys
import time

host, port, name = sys.argv[1], int(sys.argv[2]), sys.argv[3]
for attempt in range(60):
    try:
        with socket.create_connection((host, port), timeout=2):
            print(f"[entrypoint] {name} 已就绪（{host}:{port}）", flush=True)
            sys.exit(0)
    except OSError:
        time.sleep(1)
print(f"[entrypoint] 等 {name}（{host}:{port}）超时", file=sys.stderr)
sys.exit(1)
PY
}

wait_for "${NGDCS_DB_HOST:-db}" "${NGDCS_DB_PORT:-3306}" "MySQL"
wait_for "${NGDCS_REDIS_HOST:-redis}" "${NGDCS_REDIS_PORT:-6379}" "Redis"

echo "[entrypoint] migrate ..."
python manage.py migrate --noinput

echo "[entrypoint] collectstatic ..."
python manage.py collectstatic --noinput

echo "[entrypoint] gunicorn 启动"
exec gunicorn webapp.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers "${GUNICORN_WORKERS:-2}" \
    --timeout "${GUNICORN_TIMEOUT:-60}" \
    --access-logfile - \
    --error-logfile -
