# 关键决策记录

> 每条决策都记下「决定了什么」和「为什么」。
> **答辩时老师问「为什么这么设计」，答案在这里。**
>
> 规则：文档与代码冲突时，以文档为准，改代码。

---

## D-001 数据库驱动用 PyMySQL，而不是 mysqlclient

- **日期**：2026-10-10
- **决定**：Django 连接 MySQL 使用 `PyMySQL`，配合 `pymysql.install_as_MySQLdb()`
- **理由**：
  1. **Windows 友好** —— `mysqlclient` 是 C 扩展，Windows 上安装需要编译环境（Visual C++ Build Tools），经常装不上；PyMySQL 是纯 Python，`pip install` 即可
  2. 本机是 Windows 开发环境，优先保证「装得上、跑得通」
- **备选方案**：`mysqlclient`（性能更好，但 Windows 安装门槛高）
- **代价 / 风险**：
  - PyMySQL 是纯 Python 实现，批量操作性能约为 mysqlclient 的 1/2 ~ 1/5
  - 需要额外安装 `cryptography`（MySQL 8 的 `caching_sha2_password` 认证需要）
- **落地方式**：项目包 `__init__.py` 中

  ```python
  import pymysql
  pymysql.install_as_MySQLdb()
  ```

- **答辩可能被问**：为什么不用官方推荐的 mysqlclient？
  → 答：Windows 环境下 C 扩展编译门槛高，PyMySQL 保证可移植性；性能差距在当前并发量级下可以忽略。

---

## D-002 降 Django 到 5.2 LTS，而不是升级 MySQL 到 8.4

- **日期**：2026-10-10
- **背景**：venv 中安装的 Django 6.1.2 连接 MySQL 8.0.41 时直接抛错：

  ```
  django.db.utils.NotSupportedError: MySQL 8.4 or later is required (found 8.0.41).
  ```

  经查 Django 官方 ticket [#36624](https://code.djangoproject.com/ticket/36624)：**Django 6.1 起将 MySQL 最低版本提高到 8.4**。这是框架源码里的硬性检查，没有任何配置项可以绕过。

- **决定**：把 venv 中的 Django 降到 **5.2 LTS**（实际安装 5.2.18）
- **理由**：
  1. **动作最小** —— 只更换 venv 中的一个包；升级 MySQL 需要下载 MSI、运行图形安装器、重启服务，并承担数据迁移风险
  2. Django 5.2 是 **LTS 版本**，维护到 2028 年，稳定性有保障
  3. Django 5.2 支持 MySQL 8.0.11+，与本机 8.0.41 匹配
  4. 毕设周期内不需要 Django 6.x 的新特性
- **备选方案**：升级 MySQL 到 8.4 LTS
- **代价 / 约束**：
  - ⚠️ **在升级 MySQL 之前，不能把 Django 升到 6.x**
  - 系统 Python 里另有一个 Django 5.0.3，与 venv 隔离；**运行项目必须使用 venv 的解释器**
- **验证结果**：降级后实测通过

  ```
  ('8.0.41', 'myproject', 'django_user@localhost', 'utf8mb4_unicode_ci')
  Django version : 5.2.18
  ```

- **答辩可能被问**：为什么不用最新版 Django？
  → 答：框架版本应在满足需求的前提下选择稳定版；5.2 是 LTS，且与本机数据库版本兼容，避免了升级数据库带来的额外风险。

---

## 编号约定

- 编号 `D-001`、`D-002`… 递增，**已记录的决策不删除**
- 如需推翻某条决策，新增一条并注明「取代 D-00X」
- 每条至少包含：日期、决定、理由、备选方案、代价 / 风险
