# -*- coding: utf-8 -*-
import os
import sys
import json
import shutil
import inspect
import importlib
import importlib.util

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QTabWidget, QAction, QComboBox,
    QDialog, QTreeWidget, QTreeWidgetItem, QHeaderView,
    QInputDialog, QMessageBox, QAbstractItemView, QListWidget,
    QListWidgetItem, QFrame
)
from qgis.PyQt.QtGui import QIcon
from qgis.core import Qgis

current_dir = os.path.dirname(__file__)
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from base_addon import BaseAddon
from i18n import LANG_EN, LANG_ZH, current_language, set_language, tr

DEFAULT_CATEGORY_FOLDERS = [
    "01_通用核心模块",
    "02_遥感影像处理",
    "03_矢量与拓扑处理",
    "04_属性与报表工具"
]

def _ensure_core_modules():
    global tr, current_language, set_language
    plugin_dir = os.path.abspath(current_dir)
    sys.path[:] = [p for p in sys.path if os.path.abspath(p) != plugin_dir]
    sys.path.insert(0, plugin_dir)

    def _load(name, required_attrs):
        module = sys.modules.get(name)
        module_file = getattr(module, "__file__", None)
        foreign = module is not None and (
            not module_file
            or os.path.abspath(os.path.dirname(module_file)) != plugin_dir
        )
        incomplete = module is not None and any(
            not hasattr(module, attr) for attr in required_attrs
        )
        if foreign or incomplete:
            sys.modules.pop(name, None)
            module = None
        if module is None:
            module = importlib.import_module(name)
        return module

    i18n_module = _load("i18n", ("tr", "current_language", "set_language"))
    base_addon_module = _load("base_addon", ("BaseAddon", "tr"))

    tr = i18n_module.tr
    current_language = i18n_module.current_language
    set_language = i18n_module.set_language
    return i18n_module, base_addon_module

class ModuleManagerDialog(QDialog):
    def __init__(self, plugin):
        super().__init__(plugin.dock_widget)
        self.plugin = plugin
        self.setWindowTitle(tr("⚙️ 模块与分类工作区管理器", "⚙️ Module & Category Manager"))
        self.resize(700, 560)
        self._build_ui()
        self._populate_tree()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        tip = QLabel(tr(
            "💡 <b>超简操作指南：</b><br>"
            "• <b>按文件夹归类：</b>选中任意模块 -> 点击下方<b>【📁 归入分类文件夹...】</b>，即可把它放进对应的功能区（左侧书签栏会自动同步）！<br>"
            "• <b>通用模块常驻 (📌)：</b>选中常用模块 -> 点击<b>【📌 切换全局常驻】</b>，无论你在左边切换到哪个分类书签，它都会一直保留显示！<br>"
            "• <b>随时隐藏/排序：</b>去掉模块前面的勾选即可隐藏该模块（无需剪切文件）；点击<b>【⬆️ 上移 / ⬇️ 下移】</b>自由调整排列顺序。",
            "💡 <b>Quick Guide:</b><br>"
            "• Select any module and click <b>[📁 Move to Category Folder...]</b> to organize modules into Left Bookmark sections.<br>"
            "• Click <b>[📌 Toggle Global Pin]</b> on core modules so they stay visible across all category bookmarks.<br>"
            "• Uncheck modules to hide them without deleting files, or use <b>[⬆️ Up / ⬇️ Down]</b> to reorder."
        ))
        tip.setWordWrap(True)
        tip.setStyleSheet("background:#E3F2FD; color:#0D47A1; padding:8px; border-radius:4px;")
        layout.addWidget(tip)

        # Top workspace preset bar
        ws_bar = QHBoxLayout()
        ws_bar.addWidget(QLabel(tr("🗂️ 当前编辑的工作区方案:", "🗂️ Active Workspace Preset:")))
        self.combo_ws = QComboBox()
        self._refresh_ws_combo()
        self.combo_ws.currentTextChanged.connect(self._on_ws_selected)
        ws_bar.addWidget(self.combo_ws, 1)

        btn_new_ws = QPushButton(tr("➕ 新建工作区方案", "➕ New Preset"))
        btn_new_ws.clicked.connect(self._create_workspace)
        ws_bar.addWidget(btn_new_ws)

        btn_new_folder = QPushButton(tr("📁 新建分类文件夹", "📁 New Folder"))
        btn_new_folder.clicked.connect(self._create_category_folder)
        ws_bar.addWidget(btn_new_folder)

        btn_del_ws = QPushButton(tr("🗑️ 删除方案", "🗑️ Delete"))
        btn_del_ws.clicked.connect(self._delete_workspace)
        ws_bar.addWidget(btn_del_ws)
        layout.addLayout(ws_bar)

        # Module tree grouped by category folder
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([
            tr("模块名称 / 所属分类文件夹", "Module / Category Folder"),
            tr("常驻属性", "Pin Mode"),
            tr("文件位置", "File Path"),
            tr("排序号", "Order")
        ])
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        layout.addWidget(self.tree, 1)

        # Quick action bar
        ctrl_bar = QHBoxLayout()
        btn_all = QPushButton(tr("☑️ 全选", "☑️ All"))
        btn_all.clicked.connect(lambda: self._set_all_checked(True))
        btn_none = QPushButton(tr("⬜ 全不选", "⬜ None"))
        btn_none.clicked.connect(lambda: self._set_all_checked(False))

        btn_pin = QPushButton(tr("📌 切换全局常驻(通用)", "📌 Toggle Global Pin"))
        btn_pin.setStyleSheet("color: #D84315; font-weight: bold; padding: 4px 8px;")
        btn_pin.clicked.connect(self._toggle_pin_selected)

        btn_up = QPushButton(tr("⬆️ 上移", "⬆️ Up"))
        btn_up.clicked.connect(lambda: self._move_selected(-1))
        btn_down = QPushButton(tr("⬇️ 下移", "⬇️ Down"))
        btn_down.clicked.connect(lambda: self._move_selected(1))

        btn_move_folder = QPushButton(tr("📁 归入分类文件夹...", "📁 Move to Category Folder..."))
        btn_move_folder.setStyleSheet("color: #1565C0; font-weight: bold; padding: 4px 10px;")
        btn_move_folder.clicked.connect(self._move_to_subfolder)

        ctrl_bar.addWidget(btn_all)
        ctrl_bar.addWidget(btn_none)
        ctrl_bar.addWidget(btn_pin)
        ctrl_bar.addStretch()
        ctrl_bar.addWidget(btn_up)
        ctrl_bar.addWidget(btn_down)
        ctrl_bar.addWidget(btn_move_folder)
        layout.addLayout(ctrl_bar)

        # Bottom save / cancel bar
        bottom_bar = QHBoxLayout()
        bottom_bar.addStretch()
        btn_save = QPushButton(tr("✅ 保存配置并立即刷新界面", "✅ Save & Reload UI"))
        btn_save.setStyleSheet(
            "QPushButton { background-color: #2E7D32; color: white; font-weight: bold; padding: 8px 18px; border-radius: 4px; }"
        )
        btn_save.clicked.connect(self._save_and_apply)

        btn_cancel = QPushButton(tr("关闭", "Close"))
        btn_cancel.setStyleSheet("padding: 8px 14px;")
        btn_cancel.clicked.connect(self.reject)

        bottom_bar.addWidget(btn_save)
        bottom_bar.addWidget(btn_cancel)
        layout.addLayout(bottom_bar)

    def _current_ws_key(self):
        ws_dict = self.plugin.config.setdefault("workspaces", {})
        if not ws_dict:
            ws_dict["🌟 全部模块 (All)"] = {"disabled": []}
        active = self.plugin.config.get("active_workspace", "")
        if active not in ws_dict:
            active = next(iter(ws_dict.keys()))
            self.plugin.config["active_workspace"] = active
        return active

    def _refresh_ws_combo(self):
        self.combo_ws.blockSignals(True)
        self.combo_ws.clear()
        workspaces = self.plugin.config.get("workspaces", {})
        for ws_name in workspaces.keys():
            self.combo_ws.addItem(ws_name)
        active = self._current_ws_key()
        idx = self.combo_ws.findText(active)
        if idx >= 0:
            self.combo_ws.setCurrentIndex(idx)
        self.combo_ws.blockSignals(False)

    def _save_current_tree_to_ws(self, ws_name):
        if not ws_name or self.tree.topLevelItemCount() == 0:
            return
        disabled = []
        custom_orders = self.plugin.config.setdefault("custom_orders", {})
        root = self.tree.invisibleRootItem()
        global_rank = 1
        for i in range(root.childCount()):
            cat_node = root.child(i)
            for j in range(cat_node.childCount()):
                ch = cat_node.child(j)
                rel_id = ch.data(0, Qt.UserRole)
                if ch.checkState(0) != Qt.Checked:
                    disabled.append(rel_id)
                custom_orders[rel_id] = global_rank
                global_rank += 1
        self.plugin.config.setdefault("workspaces", {})[ws_name] = {"disabled": disabled}

    def _populate_tree(self):
        self.tree.blockSignals(True)
        self.tree.clear()

        discovered = self.plugin.discover_all_addon_classes()
        ws_name = self.combo_ws.currentText() or self._current_ws_key()
        ws_data = self.plugin.config.get("workspaces", {}).get(ws_name, {})
        disabled_list = set(ws_data.get("disabled", []))
        custom_orders = self.plugin.config.get("custom_orders", {})
        pinned_set = set(self.plugin.config.get("pinned_modules", []))

        # List every category subfolder on disk, including empty ones, so the tree mirrors the layout
        groups = {"": []}
        for folder in self.plugin.get_all_subfolders(include_empty=True):
            groups[folder] = []

        for item in discovered:
            cat = item["category"]
            groups.setdefault(cat, []).append(item)

        for cat_name in sorted(groups.keys()):
            items = groups[cat_name]
            cat_node = QTreeWidgetItem(self.tree)
            if cat_name == "":
                cat_label = tr(f"📦 addons 根目录 ({len(items)} 个模块)", f"📦 addons/ Root ({len(items)} modules)")
            else:
                cat_label = f"📂 {cat_name} ({len(items)})"
            cat_node.setText(0, cat_label)
            cat_node.setFlags(cat_node.flags() | Qt.ItemIsAutoTristate | Qt.ItemIsUserCheckable)
            cat_node.setExpanded(True)

            items.sort(key=lambda x: custom_orders.get(x["rel_id"], x["default_order"]))

            for info in items:
                child = QTreeWidgetItem(cat_node)
                title_str = getattr(info["cls"], "title", info["cls"].__name__)
                rel_id = info["rel_id"]
                is_pinned = (rel_id in pinned_set) or rel_id.endswith("99_module_studio.py")

                child.setText(0, title_str)
                child.setText(1, tr("📌 全局常驻", "📌 Pinned") if is_pinned else tr("普通", "Normal"))
                child.setText(2, rel_id)
                eff_order = custom_orders.get(rel_id, info["default_order"])
                child.setText(3, str(eff_order))
                child.setData(0, Qt.UserRole, rel_id)

                is_enabled = rel_id not in disabled_list
                child.setCheckState(0, Qt.Checked if is_enabled else Qt.Unchecked)

        self.tree.blockSignals(False)

    def _on_ws_selected(self, new_ws_name):
        if not new_ws_name:
            return
        prev_ws = self.plugin.config.get("active_workspace")
        if prev_ws and prev_ws != new_ws_name:
            self._save_current_tree_to_ws(prev_ws)
        self.plugin.config["active_workspace"] = new_ws_name
        self.plugin.config["active_nav"] = f"ws:{new_ws_name}"
        self._populate_tree()

    def _set_all_checked(self, checked):
        state = Qt.Checked if checked else Qt.Unchecked
        root = self.tree.invisibleRootItem()
        for i in range(root.childCount()):
            cat_node = root.child(i)
            for j in range(cat_node.childCount()):
                cat_node.child(j).setCheckState(0, state)

    def _toggle_pin_selected(self):
        item = self.tree.currentItem()
        if not item or not item.parent():
            QMessageBox.information(self, tr("提示", "Info"),
                                    tr("请先在列表中点击选中一个具体的模块（不要选文件夹标题行）！",
                                       "Please select a module row first!"))
            return
        rel_id = item.data(0, Qt.UserRole)
        pinned_list = self.plugin.config.setdefault("pinned_modules", [])
        if rel_id in pinned_list:
            pinned_list.remove(rel_id)
            item.setText(1, tr("普通", "Normal"))
        else:
            pinned_list.append(rel_id)
            item.setText(1, tr("📌 全局常驻", "📌 Pinned"))
        self.plugin.save_config()

    def _move_selected(self, direction):
        item = self.tree.currentItem()
        if not item or not item.parent():
            return
        parent = item.parent()
        idx = parent.indexOfChild(item)
        new_idx = idx + direction
        if new_idx < 0 or new_idx >= parent.childCount():
            return
        taken = parent.takeChild(idx)
        parent.insertChild(new_idx, taken)
        self.tree.setCurrentItem(taken)

        for i in range(parent.childCount()):
            ch = parent.child(i)
            ch.setText(3, str((i + 1) * 10))

    def _create_category_folder(self):
        name, ok = QInputDialog.getText(
            self,
            tr("📁 新建分类文件夹", "📁 New Category Folder"),
            tr("请输入新分类文件夹名称（例如：05_三调核查专项）：\n新建后会自动出现在左侧书签栏和顶栏下拉框中！",
               "Enter new folder name:")
        )
        if ok and name.strip():
            clean_name = name.strip().replace("/", "_").replace("\\", "_")
            target_dir = os.path.join(self.plugin.addons_dir, clean_name)
            os.makedirs(target_dir, exist_ok=True)
            self._populate_tree()
            self.plugin.refresh_navigation_ui()

    def _move_to_subfolder(self):
        item = self.tree.currentItem()
        if not item or not item.parent():
            QMessageBox.information(self, tr("提示", "Info"),
                                    tr("请先在列表中点击选中一个具体的模块！", "Please select a module item first!"))
            return

        rel_id = item.data(0, Qt.UserRole)
        if rel_id.endswith("99_module_studio.py"):
            QMessageBox.warning(self, tr("提示", "Notice"),
                                tr("99_module_studio 模块工坊建议保留在根目录。", "Keep Module Studio in root."))
            return

        root_opt = tr("📦 [移回 addons 根目录]", "📦 [Move to addons/ Root]")
        existing_folders = [root_opt]
        for folder in self.plugin.get_all_subfolders(include_empty=True):
            if folder not in existing_folders:
                existing_folders.append(folder)

        folder_name, ok = QInputDialog.getItem(
            self,
            tr("📁 归入分类文件夹", "📁 Move to Category Folder"),
            tr("请选择目标分类文件夹（也可以直接打字输入新文件夹名）：",
               "Select target category folder or type a new folder name:"),
            existing_folders,
            1 if len(existing_folders) > 1 else 0,
            True
        )
        if not ok:
            return

        folder_name = folder_name.strip()
        if folder_name == root_opt:
            folder_name = ""

        old_abs = os.path.join(self.plugin.addons_dir, rel_id)
        fname = os.path.basename(rel_id)

        if folder_name:
            folder_name = folder_name.replace("/", "_").replace("\\", "_")
            target_dir = os.path.join(self.plugin.addons_dir, folder_name)
            os.makedirs(target_dir, exist_ok=True)
            new_abs = os.path.join(target_dir, fname)
            new_rel_id = f"{folder_name}/{fname}"
        else:
            new_abs = os.path.join(self.plugin.addons_dir, fname)
            new_rel_id = fname

        if os.path.abspath(old_abs) == os.path.abspath(new_abs):
            return

        try:
            shutil.move(old_abs, new_abs)
            pinned = self.plugin.config.get("pinned_modules", [])
            if rel_id in pinned:
                pinned.remove(rel_id)
                pinned.append(new_rel_id)
            for ws_cfg in self.plugin.config.get("workspaces", {}).values():
                dis = ws_cfg.get("disabled", [])
                if rel_id in dis:
                    dis.remove(rel_id)
                    dis.append(new_rel_id)
            self.plugin.save_config()
            self._populate_tree()
            self.plugin.refresh_navigation_ui()
            self.plugin.load_all_addons()
        except Exception as e:
            QMessageBox.critical(self, tr("移动失败", "Move Failed"), str(e))

    def _create_workspace(self):
        self._save_current_tree_to_ws(self.combo_ws.currentText())
        name, ok = QInputDialog.getText(
            self,
            tr("➕ 新建工作区方案", "➕ New Workspace Preset"),
            tr("请输入新任务工作区名称（例如：🛩️ 航拍去黑边模式）：",
               "Enter workspace preset name:")
        )
        if ok and name.strip():
            ws_name = name.strip()
            self.plugin.config.setdefault("workspaces", {})[ws_name] = {"disabled": []}
            self.plugin.config["active_workspace"] = ws_name
            self.plugin.config["active_nav"] = f"ws:{ws_name}"
            self.plugin.save_config()
            self._refresh_ws_combo()
            self._populate_tree()
            self.plugin.refresh_navigation_ui()

    def _delete_workspace(self):
        ws_name = self.combo_ws.currentText()
        ws_dict = self.plugin.config.get("workspaces", {})
        if len(ws_dict) <= 1:
            QMessageBox.warning(self, tr("提示", "Notice"),
                                tr("至少需要保留一个工作区方案！", "At least one workspace preset must remain!"))
            return
        ws_dict.pop(ws_name, None)
        first_ws = next(iter(ws_dict.keys()))
        self.plugin.config["active_workspace"] = first_ws
        self.plugin.config["active_nav"] = f"ws:{first_ws}"
        self.plugin.save_config()
        self._refresh_ws_combo()
        self._populate_tree()
        self.plugin.refresh_navigation_ui()

    def _save_and_apply(self):
        ws_name = self.combo_ws.currentText()
        self._save_current_tree_to_ws(ws_name)
        self.plugin.config["active_workspace"] = ws_name
        self.plugin.config["active_nav"] = f"ws:{ws_name}"
        self.plugin.save_config()
        self.plugin.refresh_navigation_ui()
        self.plugin.load_all_addons()
        self.accept()

class ProToolboxPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.addons_dir = os.path.join(self.plugin_dir, "addons")
        self.config_path = os.path.join(self.addons_dir, "workspace_config.json")
        self.dock_widget = None
        self.action = None
        self.loaded_addons = []
        self.tabs = None
        self.sidebar_frame = None
        self.sidebar_list = None
        self.lbl_status = None
        self.lbl_nav = None
        self.btn_reload = None
        self.btn_manage = None
        self.btn_sidebar = None
        self.btn_quick_folder = None
        self.ws_combo = None
        self.lang_combo = None
        self._ensure_default_subfolders()
        self.config = self.load_config()

    def _ensure_default_subfolders(self):
        # Auto-create the 4 standard category folders so users don't have to
        if not os.path.exists(self.addons_dir):
            os.makedirs(self.addons_dir)
        for folder in DEFAULT_CATEGORY_FOLDERS:
            p = os.path.join(self.addons_dir, folder)
            if not os.path.exists(p):
                try:
                    os.makedirs(p, exist_ok=True)
                except Exception:
                    pass

    def get_all_subfolders(self, include_empty=True):
        folders = []
        if os.path.exists(self.addons_dir):
            for name in sorted(os.listdir(self.addons_dir)):
                full_p = os.path.join(self.addons_dir, name)
                if os.path.isdir(full_p) and not name.startswith("_") and not name.startswith("."):
                    if include_empty:
                        folders.append(name)
                    else:
                        has_py = any(f.endswith(".py") and not f.startswith("_") for f in os.listdir(full_p))
                        if has_py:
                            folders.append(name)
        return folders

    # ------------------------------------------------------------------
    # Config persistence (auto-repair corrupted or emptied legacy JSON config)
    # ------------------------------------------------------------------
    def load_config(self):
        default_workspaces = {
            "🌟 全部模块 (All)": {"disabled": []},
            "🛠️ 通用精简模式 (Core)": {
                "disabled": ["04_topology_auditor.py", "05_word_reporter.py", "06_table_to_map.py"]
            }
        }
        cfg = {
            "active_workspace": "🌟 全部模块 (All)",
            "active_nav": "ws:🌟 全部模块 (All)",
            "show_left_sidebar": True,
            "pinned_modules": ["01_auto_save.py", "99_module_studio.py"],
            "custom_orders": {},
            "workspaces": default_workspaces
        }
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    cfg.update(data)
            except Exception:
                pass

        # Hard check: if workspaces was emptied in an old config, restore defaults and write back at once
        if not isinstance(cfg.get("workspaces"), dict) or len(cfg["workspaces"]) == 0:
            cfg["workspaces"] = default_workspaces
        if "🌟 全部模块 (All)" not in cfg["workspaces"]:
            cfg["workspaces"]["🌟 全部模块 (All)"] = {"disabled": []}

        if cfg.get("active_workspace") not in cfg["workspaces"]:
            cfg["active_workspace"] = "🌟 全部模块 (All)"

        if not cfg.get("active_nav"):
            cfg["active_nav"] = f"ws:{cfg['active_workspace']}"

        self.config = cfg
        self.save_config()
        return cfg

    def save_config(self):
        if not os.path.exists(self.addons_dir):
            os.makedirs(self.addons_dir)
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[ProToolbox] Failed to save config: {e}")

    # ------------------------------------------------------------------
    # QGIS entry points
    # ------------------------------------------------------------------
    def initGui(self):
        self.action = QAction(tr("🛠️ Pro Toolbox 生产提效工具箱", "🛠️ Pro Toolbox"), self.iface.mainWindow())
        self.action.setIcon(self._plugin_icon())
        self.action.triggered.connect(self.toggle_window)
        self.iface.addPluginToMenu("Pro Toolbox", self.action)
        self.iface.addToolBarIcon(self.action)

    def unload(self):
        self.unload_all_addons()
        if self.action:
            self.iface.removePluginMenu("Pro Toolbox", self.action)
            self.iface.removeToolBarIcon(self.action)
        if self.dock_widget:
            self.iface.removeDockWidget(self.dock_widget)
            self.dock_widget.deleteLater()
            self.dock_widget = None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _plugin_icon(self):
        """Return the plugin's own icon for the toolbar action and dock window."""
        icon_path = os.path.join(self.plugin_dir, "icon.png")
        return QIcon(icon_path) if os.path.exists(icon_path) else QIcon()

    def _dock_title(self):
        return tr("Pro Toolbox 生产提效工具箱", "Pro Toolbox")

    def _status_text(self):
        return tr(f"当前显示: {len(self.loaded_addons)} 个模块", f"Showing: {len(self.loaded_addons)}")

    def apply_language(self):
        if self.action:
            self.action.setText(tr("🛠️ Pro Toolbox 生产提效工具箱", "🛠️ Pro Toolbox"))
        if self.dock_widget:
            self.dock_widget.setWindowTitle(self._dock_title())
        if self.lbl_status:
            self.lbl_status.setText(self._status_text())
        if self.lbl_nav:
            self.lbl_nav.setText(tr("🗂️ 当前功能区:", "🗂️ View:"))
        if self.btn_manage:
            self.btn_manage.setText(tr("⚙️ 模块与分类管理", "⚙️ Module Manager"))
        if self.btn_sidebar:
            shown = self.config.get("show_left_sidebar", True)
            self.btn_sidebar.setText(tr("◀ 收起左侧书签" if shown else "🔖 展开左侧书签",
                                        "◀ Hide Bookmarks" if shown else "🔖 Show Bookmarks"))
        if self.btn_reload:
            self.btn_reload.setText(tr("🔄 重新扫描加载模块", "🔄 Rescan & Reload"))
        if self.btn_quick_folder:
            self.btn_quick_folder.setText(tr("⚙️ 整理归类模块", "⚙️ Organize Modules"))
        self.refresh_navigation_ui()

    def on_language_changed(self, index):
        lang = LANG_ZH if index == 1 else LANG_EN
        if not set_language(lang):
            return
        self.apply_language()
        self.load_all_addons()
        self.iface.messageBar().pushMessage(
            tr("语言已切换", "Language switched"),
            tr("中文界面（全部模块已重新加载）", "English interface (all modules reloaded)"),
            level=Qgis.Success, duration=3
        )

    # ------------------------------------------------------------------
    # Window & Dual-Row Toolbar + Collapsible Left Bookmark Panel
    # ------------------------------------------------------------------
    def toggle_window(self):
        if not self.dock_widget:
            self.build_ui()
            self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dock_widget)
            self.dock_widget.setFloating(True)

        if self.dock_widget.isVisible():
            self.dock_widget.hide()
        else:
            self.dock_widget.show()
            self.dock_widget.raise_()

    def build_ui(self):
        self.dock_widget = QDockWidget(self._dock_title(), self.iface.mainWindow())
        self.dock_widget.setAllowedAreas(Qt.AllDockWidgetAreas)
        self.dock_widget.setWindowIcon(self._plugin_icon())

        def on_floating_changed(is_floating):
            if is_floating:
                self.dock_widget.setWindowFlags(
                    Qt.Window | Qt.WindowMinimizeButtonHint | Qt.WindowMaximizeButtonHint | Qt.WindowCloseButtonHint
                )
                self.dock_widget.show()
            else:
                self.dock_widget.setWindowFlags(Qt.Widget)
                self.dock_widget.show()

        self.dock_widget.topLevelChanged.connect(on_floating_changed)

        main_container = QWidget()
        main_layout = QVBoxLayout(main_container)
        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(5)

        # ==================== Row 1: rescan & reload + module manager + language switch + status ====================
        row1_bar = QHBoxLayout()
        row1_bar.setSpacing(6)

        self.btn_reload = QPushButton(tr("🔄 重新扫描加载模块", "🔄 Rescan & Reload"))
        self.btn_reload.setStyleSheet("padding: 4px 10px; font-weight: bold;")
        self.btn_reload.clicked.connect(self.rescan_all)

        self.btn_manage = QPushButton(tr("⚙️ 模块与分类管理", "⚙️ Module Manager"))
        self.btn_manage.setStyleSheet("padding: 4px 10px; font-weight: bold; color: #1565C0;")
        self.btn_manage.clicked.connect(self.open_module_manager)

        self.lang_combo = QComboBox()
        self.lang_combo.addItems(["🌐 English", "🌐 中文界面"])
        self.lang_combo.setCurrentIndex(1 if current_language() == LANG_ZH else 0)
        self.lang_combo.setMinimumWidth(98)
        self.lang_combo.activated.connect(self.on_language_changed)

        self.lbl_status = QLabel(self._status_text())
        self.lbl_status.setStyleSheet("color: #555; font-size: 12px;")

        row1_bar.addWidget(self.btn_reload)
        row1_bar.addWidget(self.btn_manage)
        row1_bar.addStretch()
        row1_bar.addWidget(self.lbl_status)
        row1_bar.addWidget(self.lang_combo)
        main_layout.addLayout(row1_bar)

        # ==================== Row 2: collapse/expand left bookmarks + active view combo ====================
        row2_bar = QHBoxLayout()
        row2_bar.setSpacing(6)

        shown = self.config.get("show_left_sidebar", True)
        self.btn_sidebar = QPushButton(tr("◀ 收起左侧书签" if shown else "🔖 展开左侧书签",
                                          "◀ Hide Bookmarks" if shown else "🔖 Show Bookmarks"))
        self.btn_sidebar.setStyleSheet("padding: 4px 10px; font-weight: bold; color: #2E7D32;")
        self.btn_sidebar.clicked.connect(self.toggle_left_sidebar)

        self.lbl_nav = QLabel(tr("🗂️ 当前功能区:", "🗂️ View:"))
        self.lbl_nav.setStyleSheet("font-weight: bold; color: #333;")

        self.ws_combo = QComboBox()
        self.ws_combo.setMinimumWidth(200)
        self.ws_combo.setStyleSheet("padding: 3px 6px; font-weight: bold;")
        self.ws_combo.currentIndexChanged.connect(self.on_top_combo_switched)

        row2_bar.addWidget(self.btn_sidebar)
        row2_bar.addWidget(self.lbl_nav)
        row2_bar.addWidget(self.ws_combo, 1)
        main_layout.addLayout(row2_bar)

        # ==================== Body: fully collapsible left bookmark panel + right module tabs ====================
        body_layout = QHBoxLayout()
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(6)

        # Left bookmark container (wrapped in QFrame, collapsing hides it fully with no blank gap!)
        self.sidebar_frame = QFrame()
        self.sidebar_frame.setFixedWidth(168)
        self.sidebar_frame.setStyleSheet(
            "QFrame { background: #F8FAFC; border: 1px solid #CBD5E1; border-radius: 5px; }"
        )
        sb_layout = QVBoxLayout(self.sidebar_frame)
        sb_layout.setContentsMargins(4, 6, 4, 6)
        sb_layout.setSpacing(4)

        sb_title = QLabel(tr("🔖 功能区与分类书签", "🔖 Workspaces & Folders"))
        sb_title.setStyleSheet("font-weight: bold; color: #1E293B; font-size: 12px; border: none; padding: 2px 4px;")
        sb_layout.addWidget(sb_title)

        self.sidebar_list = QListWidget()
        self.sidebar_list.setStyleSheet(
            "QListWidget { background: transparent; border: none; font-size: 12px; }"
            "QListWidget::item { padding: 7px 6px; border-radius: 4px; margin-bottom: 2px; color: #334155; }"
            "QListWidget::item:selected { background: #1976D2; color: white; font-weight: bold; }"
            "QListWidget::item:hover:!selected { background: #E2E8F0; }"
        )
        self.sidebar_list.currentRowChanged.connect(self.on_sidebar_row_changed)
        sb_layout.addWidget(self.sidebar_list, 1)

        self.btn_quick_folder = QPushButton(tr("⚙️ 整理归类模块", "⚙️ Organize Modules"))
        self.btn_quick_folder.setStyleSheet(
            "QPushButton { background: #E2E8F0; color: #1E293B; font-weight: bold; padding: 5px; border-radius: 4px; border: none; }"
            "QPushButton:hover { background: #CBD5E1; }"
        )
        self.btn_quick_folder.clicked.connect(self.open_module_manager)
        sb_layout.addWidget(self.btn_quick_folder)

        self.sidebar_frame.setVisible(shown)

        # Module tabs on the right
        self.tabs = QTabWidget()
        self.tabs.setTabPosition(QTabWidget.North)
        self.tabs.setUsesScrollButtons(True)

        body_layout.addWidget(self.sidebar_frame)
        body_layout.addWidget(self.tabs, 1)
        main_layout.addLayout(body_layout, 1)

        self.dock_widget.setWidget(main_container)
        self.dock_widget.resize(650 if shown else 480, 680)

        self.refresh_navigation_ui()
        self.load_all_addons()

    def refresh_navigation_ui(self):
        if self.ws_combo is None or self.sidebar_list is None:
            return

        self.ws_combo.blockSignals(True)
        self.sidebar_list.blockSignals(True)
        self.ws_combo.clear()
        self.sidebar_list.clear()

        # Count modules per category folder
        discovered = self.discover_all_addon_classes()
        cat_counts = {}
        for item in discovered:
            c = item["category"]
            cat_counts[c] = cat_counts.get(c, 0) + 1

        nav_entries = []

        # 1) Workspace presets (e.g. all modules, core only)
        ws_dict = self.config.get("workspaces", {})
        if not ws_dict:
            ws_dict = {"🌟 全部模块 (All)": {"disabled": []}}
            self.config["workspaces"] = ws_dict

        for ws_name in ws_dict.keys():
            nav_id = f"ws:{ws_name}"
            label = ws_name if ws_name.startswith(("🌟", "🛠️", "🗂️", "🛩️", "🗺️")) else f"🗂️ {ws_name}"
            nav_entries.append((nav_id, label))

        # 2) Pinned core modules only
        pinned_cnt = len(self.config.get("pinned_modules", []))
        nav_entries.append(("pin:only", tr(f"📌 通用常驻模块 ({pinned_cnt})", f"📌 Pinned Core ({pinned_cnt})")))

        # 3) All physical category subfolders (including the 4 auto-created ones, with module counts)
        for folder in self.get_all_subfolders(include_empty=True):
            cnt = cat_counts.get(folder, 0)
            nav_id = f"cat:{folder}"
            nav_entries.append((nav_id, f"📂 {folder} ({cnt})"))

        # 4) Uncategorized modules in root
        root_cnt = cat_counts.get("", 0)
        nav_entries.append(("cat:__root__", tr(f"📦 根目录未归类 ({root_cnt})", f"📦 Root Uncategorized ({root_cnt})")))

        active_nav = self.config.get("active_nav", "ws:🌟 全部模块 (All)")
        selected_idx = 0

        for idx, (nav_id, label) in enumerate(nav_entries):
            self.ws_combo.addItem(label, nav_id)
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, nav_id)
            item.setToolTip(label)
            self.sidebar_list.addItem(item)
            if nav_id == active_nav:
                selected_idx = idx

        if nav_entries:
            self.ws_combo.setCurrentIndex(selected_idx)
            self.sidebar_list.setCurrentRow(selected_idx)
            self.config["active_nav"] = nav_entries[selected_idx][0]

        self.ws_combo.blockSignals(False)
        self.sidebar_list.blockSignals(False)

    def on_top_combo_switched(self, idx):
        if idx < 0 or self.ws_combo is None:
            return
        nav_id = self.ws_combo.itemData(idx)
        if not nav_id:
            return
        self._activate_nav(nav_id, sync_sidebar=True, sync_combo=False)

    def on_sidebar_row_changed(self, row):
        if row < 0 or self.sidebar_list is None:
            return
        item = self.sidebar_list.item(row)
        if not item:
            return
        nav_id = item.data(Qt.UserRole)
        if not nav_id:
            return
        self._activate_nav(nav_id, sync_sidebar=False, sync_combo=True)

    def _activate_nav(self, nav_id, sync_sidebar=True, sync_combo=True):
        self.config["active_nav"] = nav_id
        if nav_id.startswith("ws:"):
            self.config["active_workspace"] = nav_id[3:]
        self.save_config()

        if sync_combo and self.ws_combo is not None:
            self.ws_combo.blockSignals(True)
            for i in range(self.ws_combo.count()):
                if self.ws_combo.itemData(i) == nav_id:
                    self.ws_combo.setCurrentIndex(i)
                    break
            self.ws_combo.blockSignals(False)

        if sync_sidebar and self.sidebar_list is not None:
            self.sidebar_list.blockSignals(True)
            for i in range(self.sidebar_list.count()):
                if self.sidebar_list.item(i).data(Qt.UserRole) == nav_id:
                    self.sidebar_list.setCurrentRow(i)
                    break
            self.sidebar_list.blockSignals(False)

        self.load_all_addons()

    def toggle_left_sidebar(self):
        cur = self.config.get("show_left_sidebar", True)
        new_val = not cur
        self.config["show_left_sidebar"] = new_val
        self.save_config()
        if self.sidebar_frame is not None:
            self.sidebar_frame.setVisible(new_val)
        if self.btn_sidebar is not None:
            self.btn_sidebar.setText(tr("◀ 收起左侧书签" if new_val else "🔖 展开左侧书签",
                                        "◀ Hide Bookmarks" if new_val else "🔖 Show Bookmarks"))

    def rescan_all(self):
        self._ensure_default_subfolders()
        self.refresh_navigation_ui()
        self.load_all_addons()

    def open_module_manager(self):
        dlg = ModuleManagerDialog(self)
        dlg.exec_()

    # ------------------------------------------------------------------
    # Multi-Folder Addon Discovery & Loading Engine
    # ------------------------------------------------------------------
    def unload_all_addons(self):
        for addon in self.loaded_addons:
            try:
                addon.unload()
            except Exception as e:
                print(f"[ProToolbox] Failed to unload {addon.title}: {e}")
        self.loaded_addons.clear()
        if self.tabs is not None:
            self.tabs.clear()

    def discover_all_addon_classes(self):
        i18n_module, base_addon_module = _ensure_core_modules()
        tr_fn = i18n_module.tr
        base_addon_cls = base_addon_module.BaseAddon

        if not os.path.exists(self.addons_dir):
            os.makedirs(self.addons_dir)

        discovered = []
        py_files = []
        for entry in sorted(os.listdir(self.addons_dir)):
            full_path = os.path.join(self.addons_dir, entry)
            if os.path.isfile(full_path):
                if entry.endswith(".py") and not entry.startswith("_"):
                    py_files.append(("", full_path, entry))
            elif os.path.isdir(full_path) and not entry.startswith("_") and not entry.startswith("."):
                for sub_entry in sorted(os.listdir(full_path)):
                    if sub_entry.endswith(".py") and not sub_entry.startswith("_"):
                        sub_full = os.path.join(full_path, sub_entry)
                        rel_id = f"{entry}/{sub_entry}"
                        py_files.append((entry, sub_full, rel_id))

        for category, filepath, rel_id in py_files:
            safe_mod_id = rel_id[:-3].replace("/", "_").replace("\\", "_")
            module_name = f"qgis_pro_addon_{safe_mod_id}"
            try:
                spec = importlib.util.spec_from_file_location(module_name, filepath)
                module = importlib.util.module_from_spec(spec)
                module.tr = tr_fn
                module.BaseAddon = base_addon_cls
                module.current_language = i18n_module.current_language
                module.language_label = i18n_module.language_label
                module.set_language = i18n_module.set_language
                spec.loader.exec_module(module)

                for name, obj in inspect.getmembers(module, inspect.isclass):
                    if getattr(obj, "_is_pro_addon", False) and obj is not base_addon_cls and obj.__name__ != "BaseAddon":
                        default_order = getattr(obj, "order", 99)
                        discovered.append({
                            "cls": obj,
                            "category": category,
                            "filepath": filepath,
                            "rel_id": rel_id,
                            "default_order": default_order
                        })
            except Exception as e:
                self.iface.messageBar().pushMessage(
                    tr_fn("模块读取失败", "Failed to read addon"), f"{rel_id}: {e}",
                    level=Qgis.Warning, duration=5
                )

        return discovered

    def load_all_addons(self):
        self.unload_all_addons()
        discovered = self.discover_all_addon_classes()

        active_nav = self.config.get("active_nav", "ws:🌟 全部模块 (All)")
        custom_orders = self.config.get("custom_orders", {})
        pinned_set = set(self.config.get("pinned_modules", []))

        def _sort_key(item):
            rel_id = item["rel_id"]
            if rel_id.endswith("99_module_studio.py"):
                return (9999, 9999, rel_id)
            pin_priority = 0 if rel_id in pinned_set else 1
            user_ord = custom_orders.get(rel_id, item["default_order"])
            return (pin_priority, user_ord, item["default_order"], rel_id)

        discovered.sort(key=_sort_key)

        filtered = []
        if active_nav.startswith("ws:"):
            ws_name = active_nav[3:]
            ws_data = self.config.get("workspaces", {}).get(ws_name, {})
            disabled_set = set(ws_data.get("disabled", []))
            for info in discovered:
                if info["rel_id"] not in disabled_set:
                    filtered.append(info)
        elif active_nav.startswith("cat:"):
            target_cat = active_nav[4:]
            if target_cat == "__root__":
                target_cat = ""
            for info in discovered:
                rel_id = info["rel_id"]
                if info["category"] == target_cat or rel_id in pinned_set or rel_id.endswith("99_module_studio.py"):
                    filtered.append(info)
        elif active_nav == "pin:only":
            for info in discovered:
                rel_id = info["rel_id"]
                if rel_id in pinned_set or rel_id.endswith("99_module_studio.py"):
                    filtered.append(info)
        else:
            filtered = discovered

        for info in filtered:
            cls = info["cls"]
            try:
                addon_instance = cls(self.iface, self.dock_widget, self.plugin_dir)
                tab_widget = QWidget()
                addon_instance.setup_ui(tab_widget)

                tab_idx = self.tabs.addTab(tab_widget, addon_instance.title)
                tip_parts = []
                if info["rel_id"] in pinned_set:
                    tip_parts.append(tr("📌 全局常驻通用模块", "📌 Pinned Core Module"))
                if info["category"]:
                    tip_parts.append(f"📂 {info['category']}")
                if tip_parts:
                    self.tabs.setTabToolTip(tab_idx, " | ".join(tip_parts) + f" — {addon_instance.title}")

                self.loaded_addons.append(addon_instance)
            except Exception as e:
                self.iface.messageBar().pushMessage(
                    tr("模块启动失败", "Failed to start addon"),
                    f"{getattr(cls, 'title', cls.__name__)}: {e}",
                    level=Qgis.Critical, duration=5
                )

        if self.lbl_status is not None:
            self.lbl_status.setText(self._status_text())