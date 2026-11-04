"""生成 / 更新黄金基线（`tests/baselines/golden_default.json`）。

## 什么时候该跑它

**只在故意改变默认行为时**。典型场景：

- 确实要调整占位实体的速度/出生点（那会改变 E9 的字节基线 → 必须重跑 E9）
- 协议字段有变化（更严重，所有实验都要重跑）

## 跑完必须做的事

1. `git diff tests/baselines/golden_default.json` —— 看清**到底变了什么**
2. 如果 SHA256 变了，判断要不要重跑相关实验
3. 在提交信息里写明"为什么改基线"

**随便跑它来让测试变绿是错误的用法。** 基线变绿只说明"代码和基线一致"，
不说明"实验还能复现"。

用法：

    .venv\\Scripts\\python.exe -X utf8 -m tools.gen_golden_baseline
"""

from __future__ import annotations

import sys

from tests.test_golden_baseline import BASELINE_PATH, fingerprint


def main() -> None:
    print("⚠️  只在**故意**改变默认行为时运行本脚本。")
    print("   跑完请用 git diff 看清变化，并在提交信息里说明原因。")
    print()

    old_sha = None
    if BASELINE_PATH.exists():
        import json

        try:
            old_sha = json.loads(BASELINE_PATH.read_text(encoding="utf-8")).get("sha256")
        except (ValueError, OSError):
            old_sha = None

    data = fingerprint()
    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    import json

    BASELINE_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"  写入 {BASELINE_PATH}")
    print(f"  每帧长度集合 : {data['payload_len_unique']}")
    print(f"  200 帧总字节 : {data['total_bytes']}")
    print(f"  新 SHA256    : {data['sha256']}")
    if old_sha:
        print(f"  旧 SHA256    : {old_sha}")
        print("  变化         : " + ("**已改变**" if old_sha != data["sha256"] else "无变化"))
    print()
    print("  下一步：git diff tests/baselines/golden_default.json")
    sys.exit(0)


if __name__ == "__main__":
    main()