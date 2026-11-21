# -*- coding: utf-8 -*-
import os
import sys
import inspect
import importlib.util

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (QDockWidget, QWidget, QVBoxLayout, QHBoxLayout,
                                 QPushButton, QLabel, QTabWidget, QAction, QComboBox)
from qgis.core import Qgis

# Keep the plugin directory on sys.path so addons can import BaseAddon / i18n directly.
current_dir = os.path.dirname(__file__)
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from base_addon import BaseAddon
from i18n import LANG_EN, LANG_ZH, current_language, set_language, tr


class ProToolboxPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.addons_dir = os.path.join(self.plugin_dir, "addons")
        self.dock_widget = None
        self.action = None
        self.loaded_addons = []
        self.tabs = None
        self.lbl_status = None
        self.btn_reload = None
        self.lang_combo = None

    # ------------------------------------------------------------------
    # QGIS entry points
    # ------------------------------------------------------------------
    def initGui(self):
        """Called by QGIS when the plugin is enabled."""
        self.action = QAction(tr("🛠️ Pro Toolbox 生产提效工具箱", "🛠️ Pro Toolbox"), self.iface.mainWindow())
        self.action.triggered.connect(self.toggle_window)
        self.iface.addPluginToMenu("Pro Toolbox", self.action)
        self.iface.addToolBarIcon(self.action)

    def unload(self):
        """Called by QGIS when the plugin is disabled or QGIS quits."""
        self.unload_all_addons()

        if self.action:
            self.iface.removePluginMenu("Pro Toolbox", self.action)
            self.iface.removeToolBarIcon(self.action)

        if self.dock_widget:
            self.iface.removeDockWidget(self.dock_widget)
            self.dock_widget.deleteLater()
            self.dock_widget = None

    # ------------------------------------------------------------------
    # Small helpers shared by the language switch
    # ------------------------------------------------------------------
    def _dock_title(self):
        return tr("Pro Toolbox 生产提效工具箱", "Pro Toolbox")

    def _status_text(self):
        return tr(f"已加载模块: {len(self.loaded_addons)} 个",
                  f"Loaded modules: {len(self.loaded_addons)}")

    def apply_language(self):
        """Refresh the few strings that live outside the rebuildable tabs."""
        if self.action:
            self.action.setText(tr("🛠️ Pro Toolbox 生产提效工具箱", "🛠️ Pro Toolbox"))

        if self.dock_widget:
            self.dock_widget.setWindowTitle(self._dock_title())

        if self.lbl_status:
            self.lbl_status.setText(self._status_text())

        if self.btn_reload:
            self.btn_reload.setText(tr("🔄 重新扫描加载模块", "🔄 Rescan addons"))
            self.btn_reload.setToolTip(tr(
                "往 addons 文件夹放入新模块后，点击此按钮即可立即生效",
                "Drop a new module into addons/ and click to load it instantly"))

        if self.lang_combo:
            self.lang_combo.setToolTip(tr(
                "界面语言：切换后立即重新加载全部模块",
                "Interface language: reloads every module instantly"))

    def on_language_changed(self, index):
        """Toolbar selector handler: switch language, then remount everything."""
        lang = LANG_ZH if index == 1 else LANG_EN
        if not set_language(lang):
            return

        # 1) Non-tab strings (menu action, dock title, status bar, buttons).
        self.apply_language()
        # 2) Re-execute every addon module and rebuild all tabs in the new language.
        self.load_all_addons()

        self.iface.messageBar().pushMessage(
            tr("语言已切换", "Language switched"),
            tr("中文界面（全部模块已重新加载）", "English interface (all modules reloaded)"),
            level=Qgis.Success, duration=3)

    # ------------------------------------------------------------------
    # Window
    # ------------------------------------------------------------------
    def toggle_window(self):
        """Show / hide the floating toolbox."""
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
        """Build the dock: status bar, language selector, rescan button, tabs."""
        self.dock_widget = QDockWidget(self._dock_title(), self.iface.mainWindow())
        self.dock_widget.setAllowedAreas(Qt.AllDockWidgetAreas)

        def on_floating_changed(is_floating):
            if is_floating:
                self.dock_widget.setWindowFlags(
                    Qt.Window | Qt.WindowMinimizeButtonHint | Qt.WindowMaximizeButtonHint | Qt.WindowCloseButtonHint)
                self.dock_widget.show()
            else:
                self.dock_widget.setWindowFlags(Qt.Widget)
                self.dock_widget.show()

        self.dock_widget.topLevelChanged.connect(on_floating_changed)

        # Root container.
        main_container = QWidget()
        main_layout = QVBoxLayout(main_container)
        main_layout.setContentsMargins(4, 4, 4, 4)

        # Top bar: status label, language selector and rescan button.
        top_bar = QHBoxLayout()
        self.lbl_status = QLabel(self._status_text())
        self.lbl_status.setStyleSheet("color: #666; font-size: 12px;")

        self.lang_combo = QComboBox()
        self.lang_combo.addItems(["🌐 English", "🌐 中文"])
        self.lang_combo.setCurrentIndex(1 if current_language() == LANG_ZH else 0)
        self.lang_combo.setFixedWidth(110)
        self.lang_combo.setToolTip(tr("界面语言：切换后立即重新加载全部模块",
                                      "Interface language: reloads every module instantly"))
        self.lang_combo.activated.connect(self.on_language_changed)

        self.btn_reload = QPushButton(tr("🔄 重新扫描加载模块", "🔄 Rescan addons"))
        self.btn_reload.setToolTip(tr("往 addons 文件夹放入新模块后，点击此按钮即可立即生效",
                                      "Drop a new module into addons/ and click to load it instantly"))
        self.btn_reload.setStyleSheet("padding: 3px 8px; font-weight: bold;")
        self.btn_reload.clicked.connect(self.load_all_addons)

        top_bar.addWidget(self.lbl_status)
        top_bar.addStretch()
        top_bar.addWidget(self.lang_combo)
        top_bar.addWidget(self.btn_reload)
        main_layout.addLayout(top_bar)

        # Tab pages.
        self.tabs = QTabWidget()
        self.tabs.setTabPosition(QTabWidget.North)
        self.tabs.setUsesScrollButtons(True)
        main_layout.addWidget(self.tabs)

        self.dock_widget.setWidget(main_container)
        self.dock_widget.resize(400, 650)

        # Scan and mount every addon module.
        self.load_all_addons()

    # ------------------------------------------------------------------
    # Addon engine
    # ------------------------------------------------------------------
    def unload_all_addons(self):
        """Ask every addon to release timers / shortcuts / threads, then drop tabs."""
        for addon in self.loaded_addons:
            try:
                addon.unload()
            except Exception as e:
                print(f"[ProToolbox] Failed to unload {addon.title}: {e}")
        self.loaded_addons.clear()
        if self.tabs:
            self.tabs.clear()

    def load_all_addons(self):
        """Scan addons/*.py, instantiate every addon and rebuild the tab pages."""
        self.unload_all_addons()

        if not os.path.exists(self.addons_dir):
            os.makedirs(self.addons_dir)

        addon_classes = []

        for filename in sorted(os.listdir(self.addons_dir)):
            if not filename.endswith(".py") or filename.startswith("_"):
                continue

            filepath = os.path.join(self.addons_dir, filename)
            module_name = f"qgis_pro_addon_{filename[:-3]}"

            try:
                spec = importlib.util.spec_from_file_location(module_name, filepath)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                for name, obj in inspect.getmembers(module, inspect.isclass):
                    if getattr(obj, '_is_pro_addon', False) and obj is not BaseAddon and obj.__name__ != 'BaseAddon':
                        addon_classes.append(obj)
            except Exception as e:
                self.iface.messageBar().pushMessage(
                    tr("模块读取失败", "Failed to read addon"), f"{filename}: {e}",
                    level=Qgis.Warning, duration=5
                )

        # Sort by the numeric ``order`` attribute (lowest first).
        addon_classes.sort(key=lambda cls: getattr(cls, 'order', 99))

        for cls in addon_classes:
            try:
                addon_instance = cls(self.iface, self.dock_widget, self.plugin_dir)
                tab_widget = QWidget()
                addon_instance.setup_ui(tab_widget)
                self.tabs.addTab(tab_widget, addon_instance.title)
                self.loaded_addons.append(addon_instance)
            except Exception as e:
                self.iface.messageBar().pushMessage(
                    tr("模块启动失败", "Failed to start addon"),
                    f"{getattr(cls, 'title', cls.__name__)}: {e}",
                    level=Qgis.Critical, duration=5
                )

        self.lbl_status.setText(self._status_text())
