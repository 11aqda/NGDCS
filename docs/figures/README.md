# 图表索引（docs/figures/）

> **命名约定：文件名里的编号 = 论文里的图号。**
> 写论文时找「图 6-15」→ 直接看 `fig6-15-*.png`，不用记别的。
>
> 本目录**同时放两类图**，靠「来源」一列区分：
> - 🤖 **脚本生成** —— 由 `tools/plot.py` 从 CSV 数据生成，**可复现**
> - 📷 **手工截图** —— Wireshark / 游戏界面截图，**不可复现**（需重跑实验重新截）

## 一、总览

| 图号 | 内容 | 类型 | 来源实验 | 生成方式 | 状态 |
|---|---|---|---|---|---|
| 图 6-1 | 二进制 vs JSON 包大小 | 柱状 | E1 | 🤖 `plot_e1` | ✅ `fig6-01-encoder-snapshot-size.png` |
| 图 6-2 | 编码耗时对比 | 柱状 | E1 | 🤖 `plot_e1` | ✅ `fig6-02-encoder-ser-time.png` |
| 图 6-3 | 编码方式对 CPU 的影响 | 折线 | E1 | 🤖 `plot_e1` | ✅ `fig6-03-encoder-cpu.png` |
| 图 6-4 | 连接数 vs CPU/内存 | 双轴折线 | E2 | 🤖 待写 | ⬜ 未做 |
| 图 6-5 | 连接数 vs tick 耗时 | 折线 | E2 | 🤖 待写 | ⬜ 未做 |
| 图 6-6 | RTT 分位数（P50/P95/P99） | 折线 | E2 | 🤖 待写 | ⬜ 未做 |
| 图 6-7 | IO 模型资源对比 | 折线 | E3 | — | ⬜ 只做理论讨论 |
| 图 6-8 | 丢包率 vs 插值误差 | 折线 | E4 | 🤖 待写 | ⬜ 未做（缺 `err_px`） |
| 图 6-9 | 延迟 vs 插值误差 | 折线 | E4 | 🤖 待写 | ⬜ 未做（缺 `err_px`） |
| 图 6-10 | 丢包 × 延迟 热力图 | 热力图 | E4 | 🤖 待写 | ⬜ 未做（缺 `err_px`） |
| 图 6-11 | tick 率 vs 带宽 | 折线 | E5 | 🤖 待写 | ⬜ 未做 |
| 图 6-12 | tick 率 vs 插值误差 | 折线 | E5 | 🤖 待写 | ⬜ 未做（缺 `err_px`） |
| 图 6-13 | 三种快照策略带宽对比 | 柱状 | E6 | — | ⬜ 只做理论讨论 |
| 图 6-14 | 抓包总览 | 事件时间线 | E7 | 🤖 `plot_e7` | ✅ `fig6-14-capture-overview.png` |
| 图 6-15 | 快照报文逐字段标注 | 十六进制+表格 | E7 | 🤖 `plot_e7` | ✅ `fig6-15-frame-header.png` |
| 图 6-16 | 粘包 / 半包解析对比 | **截图** | E7 | 📷 Wireshark | ⬜ 未做 |
| 图 6-17 | 实体数 vs 单帧耗时（按阶段拆解） | 多线 | E9 | 🤖 `plot_e9` | ✅ `fig6-17-entities-vs-tick.png` |
| 图 6-18 | 实体数 vs 带宽 | 折线 | E9 | 🤖 `plot_e9` | ✅ `fig6-18-entities-vs-bandwidth.png` |
| 图 6-19 | 实体数 vs 单核占用 | 折线 | E9 | 🤖 `plot_e9` | ✅ `fig6-19-entities-vs-cpu.png` |
| 图 6-20 | 单帧耗时构成占比 | 100% 堆叠柱 | E9 | 🤖 `plot_e9` | ✅ `fig6-20-time-composition.png` |

**合计 20 张**（与 `03-实验清单.md §6` 一致）。

## 二、手工截图的存放规则

| 图号 | 请存成这个文件名 |
|---|---|
| 图 6-14 | `fig6-14-capture-overview.png` |
| 图 6-15 | `fig6-15-frame-header.png` |
| 图 6-16 | `fig6-16-sticky-half-packet.png` |

> **2026-10-27 变更**：图 6-14 / 6-15 原计划是 Wireshark 截图，实际改成了
> **`tools/plot_e7.py` 从抓包文件生成**（`03 §6` 里标的"截图"类型因此变成"生成图"）。
>
> **为什么改**：截图里框不齐、字号小、夹着桌面，而且**不可复现**（重抓一次标注就废了）。
> 生成图的数据**直接来自抓包文件的字节**（TShark 读），既是真实数据又干净可重出。
>
> **原始截图保留为证据**：`_raw-fig6-14.png` / `_raw-fig6-15.png`。
> 答辩若被问"这是真抓的还是画的"，把原图拿出来即可。
>
> **重新生成**：
> ```powershell
> .venv\Scripts\python.exe -X utf8 -m tools.plot_e7 --pcap data/E7-capture.pcapng
> ```
> （依赖 `D:\Tools\Wireshark\tshark.exe`，路径可用 `--tshark` 覆盖）

## 三、手工截图的具体要求（图 6-16 仍走这条路）

**截图要求**（写进论文的图，质量要够）：

1. **只截目标窗口**，不要把整个桌面/浏览器/其他软件截进去
2. **用 PNG**，不要 JPG（JPG 会把文字和十六进制糊掉）
3. 分辨率尽量高，但**宽度建议 ≥ 1200 px**，论文排版缩小后仍清晰
4. 需要说明的地方，**先用 Windows 截图工具的标注功能画好**（红框/箭头），省得后期再加工

**Windows 截图方法**：`Win + Shift + S` 框选 → 打开「画图」→ `Ctrl+V` → `文件 → 另存为 → PNG` → 选上面那个路径。

## 四、脚本生成的图怎么重出

```powershell
# E9 四张（图 6-17~6-20）
.venv\Scripts\python.exe -X utf8 -m tools.plot --csv data/server_metrics.csv --out docs/figures --scenario E9-

# E1 三张（图 6-1~6-3）
.venv\Scripts\python.exe -X utf8 -m tools.plot --csv data/server_metrics.csv --out docs/figures --scenario E1-
```

> ⚠️ **必须带 `--scenario` 前缀**，否则会把所有实验的数据混到一张图里。
> 原始数据在 `data/server_metrics.csv`（已 gitignore，不在仓库里）。

## 五、与论文其他部分的关系

- **图表清单**（哪个图放第几节、图注怎么写）由负责论文正文的对话维护，本文件只管**文件在哪**
- 每张图的数据来源、实验条件、异常说明，见对应的 `docs/experiments/E*.md`
- 图号对应关系以 `03-实验清单.md §6` 为准

---

**最后更新**：2026-10-27