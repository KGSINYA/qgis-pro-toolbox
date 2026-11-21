# -*- coding: utf-8 -*-
"""Pro Toolbox addon template.

Usage: copy this file to ``addons/07_my_tool.py`` (drop the underscore prefix),
then click "🔄 Rescan addons" at the top of the dock — the new tab appears instantly.

Files starting with an underscore are skipped by the loader in main.py, so this
template never activates even though it stays in the repository.
"""
from qgis.PyQt.QtWidgets import QLabel, QPushButton, QVBoxLayout

from base_addon import BaseAddon, tr


class TemplateAddon(BaseAddon):
    """Minimal working addon: one title, one button, one unload hook."""

    title = tr("🧩 模板模块", "🧩 Template addon")
    order = 7

    def setup_ui(self, parent_widget):
        layout = QVBoxLayout(parent_widget)

        layout.addWidget(QLabel(tr(
            "把 addons/_template_addon.py 复制成 07_my_tool.py，",
            "Copy addons/_template_addon.py to 07_my_tool.py,")))
        layout.addWidget(QLabel(tr(
            "再点 Dock 顶部的「🔄 重新扫描加载模块」即可看到新 Tab。",
            'then click "🔄 Rescan addons" at the top of the dock to see the new tab.')))
        layout.addSpacing(8)

        btn = QPushButton(tr("测试 QGIS 消息栏", "Test QGIS message bar"))
        btn.clicked.connect(self._hello)
        layout.addWidget(btn)

        layout.addStretch()

    def _hello(self):
        self.iface.messageBar().pushMessage(
            "Pro Toolbox",
            tr("热插拔成功：这个 Tab 没有改过一行 main.py。",
               "Hot-swap works: this tab was added without touching main.py."),
            level=0,
            duration=3,
        )

    def unload(self):
        """Clean up on unload/reload: stop QTimers, unregister QShortcuts, quit QThreads, disconnect signals."""
        pass
