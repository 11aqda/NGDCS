"""打印 E5 清单里的关键数字，方便抄进实验文档（避免手抄出错）。"""

import json
from pathlib import Path

manifest = Path("data/runs/E5-manifest.json")
data = json.loads(manifest.read_text(encoding="utf-8"))

print(f"档位 {data['tiers']}  轮数 {data['reps']}  采样 {data['sample_s']:.0f}s")
print(f"实体 {data['entities']}")
print()
header = f"{'场景':<14}{'带宽KB/s':>10}{'CPU%':>7}{'tick_ms':>9}{'p95_ms':>8}{'预算%':>7}{'快照B':>8}"
print(header)
print("-" * len(header))

for run in data["runs"]:
    print(
        f"{run['scenario']:<14}"
        f"{run.get('bandwidth_kbps', 0):>10.2f}"
        f"{run.get('cpu_percent', 0):>7.2f}"
        f"{run.get('tick_mean_ms', 0):>9.3f}"
        f"{run.get('tick_p95_ms', 0):>8.3f}"
        f"{run.get('budget_used_percent', 0):>7.1f}"
        f"{run.get('snapshot_bytes', 0):>8.0f}"
    )

print()
print("档位均值与每 Hz 带宽：")
for hz in data["tiers"]:
    group = [r for r in data["runs"] if r["tick_hz"] == hz and r.get("ok")]
    if not group:
        continue

    def mean(key):
        vals = [r[key] for r in group if isinstance(r.get(key), (int, float))]
        return sum(vals) / len(vals) if vals else None

    bw = mean("bandwidth_kbps")
    print(
        f"  {hz:>2} Hz: 带宽 {bw:6.2f} KB/s (每 Hz {bw / hz:.3f})，"
        f"CPU {mean('cpu_percent'):4.2f}%，"
        f"tick {mean('tick_mean_ms'):.3f} ms，"
        f"预算 {mean('budget_used_percent'):4.1f}%"
    )

print()
print("解析式校验（带宽 = (快照载荷 + 12B 帧头) × 玩家数 × tick 率）：")
snapshot = data["runs"][0].get("snapshot_bytes") or 0
players = data["entities"]["players"]
for hz in data["tiers"]:
    group = [r for r in data["runs"] if r["tick_hz"] == hz and r.get("ok")]
    if not group:
        continue
    bw = sum(r["bandwidth_kbps"] for r in group) / len(group)
    predicted = (snapshot + 12) * players * hz / 1024
    print(
        f"  {hz:>2} Hz: 实测 {bw:7.2f} / 解析 {predicted:7.2f} KB/s  "
        f"误差 {(bw - predicted) / predicted * 100:+5.2f}%"
    )