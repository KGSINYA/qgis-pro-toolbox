# 安全与合规审计报告

> 对象：**Pro Toolbox（qgis_pro_tools）** — 热插拔式 QGIS 生产提效工具箱
> 版本：v1.0.0 ｜ 审计日期：2026-11-19 ｜ 范围：仓库内根目录文件 + `addons/` + `metadata.txt` + `build_zip.py`（`libs/` 为第三方 wheel 与解压产物，单独说明）
> 结论：**未发现公司名、内网 IP、涉密项目名、硬编码个人路径或任何网络/遥测代码**。审计发现的 1 处工号残留、全部身份占位符与 113 个含本机用户名的字节码缓存均已清除；3 处代码缺陷中 2 处已修复、1 处为死代码待定。

---

## 1. 脱敏扫描

### 1.1 扫描方法

对全仓库（排除 `libs/` 第三方代码）执行关键词 grep，覆盖三类风险：

| 类别 | 匹配模式（节选） | 命中 |
|---|---|---|
| 本机/隐私路径 | `C:\\Users`、`/home/`、`/Users/`、`Desktop`、`Administrator`、`[A-Za-z]:[\\/]` | 0（业务代码） |
| 网络地址 | IPv4 字面量、`http://`、`https://`、`192.168.`、`10.`、`172.16-31.` | 0（业务代码，仅注释/文档 URL） |
| 组织/涉密信息 | 公司、集团、研究院、省、市、项目代号、涉密、保密 | 0 |
| 联系方式 | QQ 号、手机号、`@qq.com` | 0 |
| 外联能力 | `urllib`、`requests`、`QNetwork`、`socket`、`subprocess`、`eval`、`exec` | 0 |

> 说明：`libs/` 下第三方包内的 `http(s)://` 均为其源码注释中的 W3C/微软规范链接，不产生运行时请求，已在统计中剔除。

### 1.2 命中项逐条判定

| 位置 | 内容 | 判定 |
|---|---|---|
| `metadata.txt:7` | `author=KGSINYA` | ✅ 保留（作者署名，公开信息） |
| `metadata.txt:8` | `email=kgsinya@163.com` | ✅ 保留（QGIS 官方要求必填，用于接收审核通知） |
| `addons/05_excel_map.py:118`、`:529` | 「测绘…坐标填反」 | ✅ 通用地理术语，非涉密 |
| `addons/06_word_report.py:25` | 「【内网离线免安装引擎】」 | ✅ 技术描述（强调不联网），可保留 |
| `addons/02_layer_switch.py:58-59` | 图层组默认名「影像对比」 | ✅ 通用遥感对比场景 |
| `addons/04_qaqc.py` | 字段 `QA_Status` | ✅ 通用质检字段，无业务耦合 |

### 1.3 已消除的 PII

| 位置 | 原内容 | 处理 |
|---|---|---|
| `metadata.txt:7` | `author=〈原姓名〉（〈4 位工号〉）` | 已删除工号（PII），并按发布者确认改用 `KGSINYA` 署名 |

### 1.4 数据落盘风险（已在 `.gitignore` 处理）

插件运行时会写出两类**可能含业务数据**的文件，发布/提交前必须确认它们不会被误提交：

- `Backup_%Y%m%d_%H%M%S/` —— 自动存档快照（`.gpkg`），可能含真实图层数据；
- `numpad_macro_config.json` —— 用户自定义宏文本，可能含业务字段名或内部话术。

`.gitignore` 已同时忽略两者。**注意：删除 `.gitignore` 规则或使用 `git add -f` 会绕过保护。**

---

### 1.5 构建缓存清理

`__pycache__` 里的 `.pyc` 会把编译时的绝对路径（`C:\Users\<本机用户名>\...`）写进字节码 —— 这是一条容易被忽略的 PII 泄漏通道。本次已删除全部 **113 个**缓存文件：

- `addons/__pycache__/`：18 个（11 个 `cpython-39` 历史遗留 + 7 个本次语法检查生成）；
- `libs/**/__pycache__/`：95 个（第三方包首次运行解压时生成）。

这些文件本就被 `.gitignore` 忽略、`build_zip.py` 也不会打包；删除后 QGIS 下次运行会自动重建，不影响功能。删除前已抽样确认 95 个 libs 缓存与 11 个 addons 缓存确实内嵌了本机用户目录。

---

## 2. 代码缺陷与修复记录

审计期间发现并修复以下问题（均为静态修复，尚未在 QGIS 内实测）：

| 级别 | 位置 | 问题 | 状态 |
|---|---|---|---|
| **P0** | `addons/06_word_report.py:531` | `spin_w = sub_w.findChild(QSpinBox, "width_spin") if spin_w else None` —— 条件引用了正在赋值的变量，触发 `UnboundLocalError`，Word 报表「外部图片」列必然崩溃 | ✅ 已修复为 `if sub_w else None` |
| **P1** | `addons/03_numpad_macro.py:14` | 模块级 `ctypes.WinDLL('user32')`，在 Linux/macOS 上 `import` 阶段即抛异常，整个模块加载失败 | ✅ 已加 `IS_WINDOWS` 守卫 + `_is_pro_addon = IS_WINDOWS`，非 Windows 由加载器自动跳过 |
| **P1** | `libs/lxml-6.1.3-cp312-cp312-win_amd64.whl` | wheel 标记 `cp312`（CPython 3.12 / Windows x64），只能用于 QGIS 3.34+ 的官方 Windows 构建；3.16–3.32（Python 3.9）上 `import lxml` 会因 ABI 不匹配失败 | ✅ 已在 README「运行时版本要求」与 `metadata.txt` 的 about 中明确说明；并给出 `pip download --python-version 3.12 / 39` 的替换命令 |
| **P2** | `addons/06_word_report.py:576-628` | `word_generate_report()` 的 `except` 分支内重复定义了 `word_refresh_layers()`（真正实现在 `:630`），属死代码，易误导维护者 | ⚠️ 建议删除，本次未改动 |
| **P2** | `main.py:74` | Dock 标题「Pro 生产提效组件 V2.0」与 `metadata.txt` 的 `version=1.0.0` 不一致 | ✅ 已统一为「Pro Toolbox 生产提效工具箱」 |

---

## 3. QGIS 官方仓库提交合规清单

依据 [QGIS 文档 16.1 插件结构 / 16.4 插件元数据](https://docs.qgis.org/3.44/en/docs/pyqgis_developer_cookbook/plugins/plugins.html)：

| 要求 | 状态 | 说明 |
|---|---|---|
| `metadata.txt` 存在且可解析 | ✅ | 无 BOM，`key=value` 格式 |
| 必填字段齐全 | ✅ | name / qgisMinimumVersion / description / about / version / author / email / **repository**（Required=True） |
| `description`、`about` 无 HTML | ✅ | 纯文本；about 多行续行用 4 空格缩进 |
| `experimental` / `deprecated` 为布尔字面量 | ✅ | 均 `False` |
| `category` 合法 | ✅ | `Vector`（取值仅 Raster/Vector/Database/Mesh/Web） |
| `tags` 逗号分隔、英文 | ✅ | `automation,digitizing,workflow,hot-reload,report,vector`（无空格） |
| ZIP 根目录为单个文件夹 | ✅ | `qgis_pro_tools/`，仅 ASCII 字母/数字/`_`/`-`，不以数字开头 |
| LICENSE 存在且**无扩展名** | ✅ | `LICENSE`（GPL-3.0 全文 + 版权声明），非 `LICENSE.txt` |
| 不含 `__pycache__` / `.git` / 解压缓存 | ✅ | `build_zip.py` 强制排除 |
| 版本号唯一 | ⚠️ 待确认 | 上传前需确认 `1.0.0` 未被同名插件占用；升级须递增 |
| 插件图标 | ✅ | `icon.png`（256×256，metadata 声明 `icon=icon.png`）|

---

## 4. 发布前必须人工完成的 5 件事

1. ✅ **已替换 GitHub 用户名占位符** → `KGSINYA`（README 7 处、`metadata.txt` 3 处）——若仓库改名需再改一次；
2. ✅ **署名已确认**：`author=KGSINYA`、`email=kgsinya@163.com`，`LICENSE` 版权行同步为 `Copyright (C) 2026 KGSINYA <kgsinya@163.com>`；
3. ✅ **图标已确认**：使用当前 `icon.png`（256×256，深色等距图层 + 琥珀色点要素），metadata 已声明 `icon=icon.png`；
4. **按目标 QGIS 的 Python 版本更新 `libs/*.whl`**（当前 lxml 为 cp312，若你的 QGIS 是 3.28 及更早版本，大概率是 Python 3.9）；
5. **在 QGIS 内做一次冒烟测试**：加载插件 → 依次打开 6 个 Tab → 各触发一次核心动作（本机未安装 QGIS，本次仅完成静态检查与 ZIP 结构校验）。

---

## 5. 个人信息填写位置（PII 清单）

| 内容 | 文件 | 行号 |
|---|---|---|
| 作者姓名 | `metadata.txt` | 7 |
| 邮箱 | `metadata.txt` | 8 |
| Issues 链接 | `metadata.txt` | 14 |
| 仓库链接 | `metadata.txt` | 15 |
| 主页链接 | `metadata.txt` | 16 |
| 版权行 `Copyright (C) 2026 KGSINYA <kgsinya@163.com>` | `LICENSE` | 2 |
| 作者表 | `README.md` | 330 |
| GitHub 用户名（4 处） | `README.md` | 13, 186, 198, 204 |
| GitHub 用户名（作者表 2 处） | `README.md` | 332, 333 |
| 插件目录 ID（若重命名仓库根目录） | `build_zip.py` | `PLUGIN_ID` 常量 |

> 建议：`tracker`/`repository`/`homepage` 三处保持同一仓库地址，否则 QGIS 插件页的「Bug Tracker」与「Source Code」会指向不同位置。

---

## 6. 关于 `qgisMinimumVersion`：3.0 → 3.16 的依据

任务说明书写的是 `3.0`，但代码实际调用了 3.10 / 3.16 才引入的 API。若声明 3.0，QGIS 3.0–3.9 用户安装后会在运行时报 `AttributeError`：

| API | 引入版本 | 调用位置 |
|---|---|---|
| `QgsVectorFileWriter.writeAsVectorFormatV3` | **3.16** | `addons/01_auto_save.py:257` |
| `QgsVectorFileWriter.writeAsVectorFormatV2` | 3.10 | `addons/01_auto_save.py:164` |
| `QgsMapCanvas.flashGeometries` | 3.10 | `addons/05_excel_map.py` |

因此 `metadata.txt` 声明 `qgisMinimumVersion=3.16`、`qgisMaximumVersion=3.99`。**这是唯一与任务书不一致的地方**，属于修正而非偏离。若必须支持 3.0，需要为上述调用增加版本分支回退（`if Qgis.QGIS_VERSION_INT >= 31600: ... else: ...`），成本约 30 行。

---

## 7. 第三方依赖许可证

`libs/` 随插件分发三个纯 wheel（不解压提交），均为 GPL 兼容许可：

| 组件 | 版本 | 许可证 | 兼容性说明 |
|---|---|---|---|
| lxml | 6.1.3 | BSD-3-Clause | 允许闭源/开源再分发，与 GPL-3.0 兼容 |
| python-docx | 1.2.0 | MIT | 同上 |
| typing_extensions | 4.16.0 | PSF-2.0 | 同上 |

插件本体以 **GPL-3.0-or-later** 发布，与 QGIS 官方强制要求一致。分发 ZIP 时保留 wheel 原始文件即可满足署名要求（wheel 的 `.dist-info` 内含许可证文本）。
