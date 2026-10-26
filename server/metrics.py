"""指标落盘：把每秒统计追加写进 CSV，供 `tools/plot.py` 出图。

对齐 `03-实验清单.md §4.1 / §4.2` 的 schema 与 §4.3 的原则：

| 原则 | 这里的做法 |
|---|---|
| 追加写，不覆盖 | `open(..., "a")`，一次实验分段跑也不丢历史 |
| 每行带 `scenario_id` | `--scenario` 参数透传，出图时按它切分 |
| 采集开销可忽略 | 每 **秒** 写一行（不是每包写磁盘），一次实验也就几百行 |
| 时间戳用单调时钟 | `t_mono`（自服务端启动的秒数）是**分析用的列** |

> **对 §4.3 的一点补充**：CSV 里同时保留 `timestamp`（本地墙上时钟，给人看的）
> 和 `t_mono`（单调时钟，给程序算的）。只留墙上时钟不安全（NTP 调整会让时间倒流），
> 只留单调时钟则没法跟「我是几点跑的」对上号，两列各司其职。

`psutil` 是可选的：没装就只写时间与流量，CPU / 内存两列留空并提示一次 ——
实验不会因为少一个包而跑不起来。
"""

from __future__ import annotations

import csv
import time
from pathlib import Path

try:  # psutil 只用来采 CPU / 内存，缺了不影响核心功能
    import psutil
except ImportError:  # pragma: no cover - 取决于环境
    psutil = None


METRICS_FIELDS = [
    "timestamp",
    "t_mono",
    "scenario_id",
    "client_count",
    "enemies",
    "bullets",
    "tick_ms_avg",
    "tick_ms_p95",
    "tick_ms_max",
    # tick 的四段拆解（2026-10-25 新增）：碰撞与通信必须能分开看
    "sim_ms",
    "collision_ms",
    "ser_ms",
    "net_ms",
    "hits",
    "snapshot_bytes",
    "cpu_percent",
    "cpu_seconds",
    "mem_mb",
    "packets_out",
    "bytes_out",
    "packets_in",
    "bytes_in",
]

SCENARIO_FIELDS = [
    "timestamp",
    "scenario_id",
    "encoder",
    "tick_rate",
    "enemies",
    "bullets",
    "seed",
    "inject_loss",
    "inject_delay",
]


def _open_for_append(path: Path, fields: list[str]):
    """打开 CSV 追加写；文件不存在或为空时先写表头。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    needs_header = not path.exists() or path.stat().st_size == 0
    handle = path.open("a", newline="", encoding="utf-8")
    writer = csv.DictWriter(handle, fieldnames=fields)
    if needs_header:
        writer.writeheader()
    return handle, writer


def write_scenario(
    path: str | Path,
    scenario_id: str,
    *,
    enemies: int = 0,
    bullets: int = 0,
    tick_rate: int = 20,
    seed: int = 1,
    encoder: str = "binary",
    inject_loss: float = 0.0,
    inject_delay: float = 0.0,
) -> None:
    """写一行场景信息（§4.1 的 `server_scenario.csv`）。

    `encoder` / `inject_loss` / `inject_delay` 现在固定为默认值 ——
    E1（编码对比）和 E4/E5（netem 注入）时才填真实值，先把 schema 定下来。
    """
    path = Path(path)
    handle, writer = _open_for_append(path, SCENARIO_FIELDS)
    try:
        writer.writerow(
            {
                "timestamp": _wall_clock(),
                "scenario_id": scenario_id,
                "encoder": encoder,
                "tick_rate": tick_rate,
                "enemies": enemies,
                "bullets": bullets,
                "seed": seed,
                "inject_loss": inject_loss,
                "inject_delay": inject_delay,
            }
        )
        handle.flush()
    finally:
        handle.close()


def _wall_clock() -> str:
    """本地墙上时钟，只用于人看（分析一律用 t_mono）。"""
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def cpu_percent_from_deltas(delta_cpu_s: float, delta_wall_s: float) -> float:
    """单核占用百分比：ΔCPU 秒数 ÷ Δ墙钟秒数 × 100。

    100% 就是「一个核跑满」。asyncio 服务端是单线程的，所以这个值天然不会超过 100。

    **量纲依据**：本函数的定义式（`ΔCPU秒 ÷ Δ墙钟秒 × 100`）就是单核占用的定义本身，
    不依赖任何外部基准 —— 这也是它能用来**推翻**旧数据的原因：
    `01 §7.1` 早期原型表的 CPU 列是按 200 Hz 算的（放大 10 倍），
    量纲更正见 **D-027**。当前权威数据是 E9 正式实验（9 档 × 2 轮）。

    **为什么不用 `psutil.Process.cpu_percent()`**：那个 API 把「阻塞式 interval」和
    「非阻塞增量」两种语义混在一起，非阻塞模式还要再乘一次 `cpu_count()`，量纲容易搞错；
    自己算增量，定义写在脸上，也能单测。

    **实测校验**（2026-10-24，本机）：故意忙等 0.5 s / 0.1 s、其余时间睡觉，
    分别读出 **49.95%** 和 **9.37%**，空闲读出 **0.0%** —— 量纲正确，精度优于 0.1%。

    ⚠️ **它和 `tick_ms` 不是一回事**：`tick_ms` 是 tick 主体的**墙钟**耗时，
    里面包含 `await writer.drain()` 的等待和事件循环调度；本函数算的是**真正的 CPU 时间**。
    实测 4 人 + 100 敌机 + 800 子弹时，tick_ms ≈ 1.4 ms 但 CPU 只占约 0.87 ms/tick ——
    差额是 I/O 等待。**两个都要报**：一个说「帧预算够不够」，一个说「CPU 够不够」。

    ⚠️⚠️ **低负载下单秒读数不可信**（2026-10-25 实测发现）：
    进程 CPU 时间是按调度时钟更新的（Windows 上约 15.6 ms 一跳）。
    当服务端每秒只花 ~20 ms CPU（例如 30 敌机 + 200 子弹）时，
    单行会读成 **0% 或 1.56%**，两轮实验的逐秒均值能差到 66%。
    **所以 CSV 里同时存了累计值 `cpu_seconds`**，
    由 `tools/plot.py` 用「首尾累计值之差 ÷ 首尾墙钟之差」算**整轮** CPU% ——
    那样只有两个端点各带一次量化误差，除以几分钟的时长后可以忽略。
    """
    if delta_wall_s <= 0:
        return 0.0
    return delta_cpu_s / delta_wall_s * 100.0
    if delta_wall_s <= 0:
        return 0.0
    return delta_cpu_s / delta_wall_s * 100.0


class MetricsRecorder:
    """每秒写一行服务端指标。"""

    def __init__(
        self,
        path: str | Path,
        scenario_id: str = "",
        enable_process_stats: bool = True,
    ) -> None:
        self.path = Path(path)
        self.scenario_id = scenario_id or "adhoc"
        self._t0 = time.monotonic()

        self._process = None
        self._last_cpu_total = 0.0
        self._last_wall = 0.0
        if enable_process_stats:
            self._init_process_stats()

        self._handle, self._writer = _open_for_append(self.path, METRICS_FIELDS)

    def _init_process_stats(self) -> None:
        if psutil is None:
            print("[metrics] 未安装 psutil，CPU / 内存两列将留空")
            return
        self._process = psutil.Process()
        # 记下基线：CPU 用量是「两次采样之间的增量」，没有基线就没有百分比
        cpu = self._process.cpu_times()
        self._last_cpu_total = cpu.user + cpu.system
        self._last_wall = time.monotonic()

    def _sample_process(self) -> tuple[float | str, float | str, float | str]:
        """返回 (本窗口 CPU%, **累计** CPU 秒数, 常驻内存 MB)。"""
        if self._process is None:
            return "", "", ""
        try:
            now = time.monotonic()
            cpu = self._process.cpu_times()
            mem_mb = self._process.memory_info().rss / 1024 / 1024

            cpu_total = cpu.user + cpu.system
            delta_cpu = cpu_total - self._last_cpu_total
            delta_wall = now - self._last_wall
            self._last_cpu_total = cpu_total
            self._last_wall = now
        except Exception:  # pragma: no cover - 进程信息偶发取不到
            return "", "", ""
        return (
            round(cpu_percent_from_deltas(delta_cpu, delta_wall), 2),
            round(cpu_total, 3),
            round(mem_mb, 1),
        )

    def write(
        self,
        *,
        client_count: int,
        enemies: int,
        bullets: int,
        stats: dict,
    ) -> None:
        """把 `TickStats.flush()` 的结果加上环境信息写成一行。"""
        cpu, cpu_seconds, mem_mb = self._sample_process()
        self._writer.writerow(
            {
                "timestamp": _wall_clock(),
                "t_mono": round(time.monotonic() - self._t0, 3),
                "scenario_id": self.scenario_id,
                "client_count": client_count,
                "enemies": enemies,
                "bullets": bullets,
                "tick_ms_avg": stats["avg_ms"],
                "tick_ms_p95": stats["p95_ms"],
                "tick_ms_max": stats["max_ms"],
                "sim_ms": stats["sim_ms"],
                "collision_ms": stats["collision_ms"],
                "ser_ms": stats["ser_ms"],
                "net_ms": stats["net_ms"],
                "hits": stats["hits"],
                "snapshot_bytes": stats["snapshot_bytes"],
                "cpu_percent": cpu,
                "cpu_seconds": cpu_seconds,
                "mem_mb": mem_mb,
                "packets_out": stats["packets_out"],
                "bytes_out": stats["bytes_out"],
                "packets_in": stats["packets_in"],
                "bytes_in": stats["bytes_in"],
            }
        )
        # 每行都 flush：实验中途被 Ctrl+C 也不会丢掉已经采到的数据
        self._handle.flush()

    def close(self) -> None:
        try:
            self._handle.close()
        except Exception:  # pragma: no cover
            pass