# -*- coding: utf-8 -*-
"""Pro Toolbox 模块模板。

用法：把本文件复制为 ``addons/07_my_tool.py``（去掉下划线前缀），
点击 Dock 顶部的「🔄 重新扫描加载模块」，新 Tab 立刻出现。

下划线开头的文件会被 main.py 的加载器跳过，所以本模板常驻仓库也不会生效。
"""
from qgis.PyQt.QtWidgets import QLabel, QPushButton, QVBoxLayout

from base_addon import BaseAddon


class TemplateAddon(BaseAddon):
    """最小可用模块：一个标题 + 一个按钮 + 一个卸载钩子。"""

    title = "🧩 模板模块"
    order = 7

    def setup_ui(self, parent_widget):
        layout = QVBoxLayout(parent_widget)

        layout.addWidget(QLabel("把 addons/_template_addon.py 复制成 07_my_tool.py，"))
        layout.addWidget(QLabel("再点 Dock 顶部的「🔄 重新扫描加载模块」即可看到新 Tab。"))
        layout.addSpacing(8)

        btn = QPushButton("测试 QGIS 消息栏")
        btn.clicked.connect(self._hello)
        layout.addWidget(btn)

        layout.addStretch()

    def _hello(self):
        self.iface.messageBar().pushMessage(
            "Pro Toolbox",
            "热插拔成功：这个 Tab 没有改过一行 main.py。",
            level=0,
            duration=3,
        )

    def unload(self):
        """卸载/重扫时清理资源：停 QTimer、注销 QShortcut、结束 QThread、断开信号。"""
        pass
