"""验证黄金基线本身：**它必须既确定又敏感**。

一个永远不会红的测试毫无价值。这里检查两件事：

1. **确定性**：同样的输入跑两次，SHA256 必须完全一致
2. **敏感性**：改一个无关紧要的输入（seed / 敌机数 / 玩家位置），SHA256 必须变
   —— 否则说明指纹没覆盖到那些维度，锁是漏的
"""

import tests.test_golden_baseline as g

base = g.fingerprint()
again = g.fingerprint()

print(f"  基线 SHA256        : {base['sha256']}")
print(f"  再跑一次            : {again['sha256']}")
print(f"  确定性              : " + ("✅ 一致" if base["sha256"] == again["sha256"] else "❌ 不一致"))
print()

original_seed = g.SEED
original_enemies = g.ENEMIES
original_players = g.PLAYER_XS

results = []

# ① 换 seed
g.SEED = 2
results.append(("seed 1 → 2", g.fingerprint()["sha256"]))
g.SEED = original_seed

# ② 换敌机数
g.ENEMIES = 31
results.append(("敌机 30 → 31", g.fingerprint()["sha256"]))
g.ENEMIES = original_enemies

# ③ 换一个玩家的 x（只挪 1 px）
g.PLAYER_XS = ((1, 101), (2, 260), (3, 420), (4, 580))
results.append(("玩家 1 的 x 100 → 101", g.fingerprint()["sha256"]))
g.PLAYER_XS = original_players

print("  敏感性检查（每项都应和基线不同）：")
all_sensitive = True
for label, sha in results:
    changed = sha != base["sha256"]
    all_sensitive &= changed
    print(f"    {label:<24} {'✅ 变了' if changed else '❌ 没变（锁是漏的）'}")
    print(f"      {sha[:32]}…")
print()

ok = base["sha256"] == again["sha256"] and all_sensitive
print("  结论: " + ("✅ 指纹既确定又敏感，可以用作基线" if ok else "❌ 有问题，别急着往下做"))
raise SystemExit(0 if ok else 1)