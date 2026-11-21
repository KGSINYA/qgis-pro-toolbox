# -*- coding: utf-8 -*-
from qgis.PyQt.QtWidgets import QWidget

# ``tr`` is re-exported here so addons need a single import line:
#     from base_addon import BaseAddon, tr
from i18n import current_language, language_label, set_language, tr  # noqa: F401


class BaseAddon:
    """Template that every hot-swappable addon inherits from."""

    _is_pro_addon = True
    title = tr("🧩 未命名模块", "🧩 Untitled addon")
    order = 99  # lower number = tab appears earlier

    def __init__(self, iface, dock_widget, plugin_dir):
        self.iface = iface
        self.dock_widget = dock_widget
        self.plugin_dir = plugin_dir

    def setup_ui(self, parent_widget: QWidget):
        """Draw this addon's interface inside ``parent_widget``."""
        pass

    def unload(self):
        """Release timers, shortcuts, threads and canvas markers.

        QGIS calls this on shutdown, and ``main.py`` calls it again before
        rebuilding the tabs on a language switch, so it must be safe to call
        more than once.
        """
        pass
