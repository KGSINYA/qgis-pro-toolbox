# -*- coding: utf-8 -*-
"""End-to-end smoke tests for Pro Toolbox.

Run with the QGIS Python interpreter, because the plugin imports PyQGIS::

    D:\\QGIS3.34.1\\bin\\python-qgis.bat tests\\test_plugin_smoke.py

The suite works on a throw-away copy of the plugin, so it never touches the
checked-in ``addons/workspace_config.json`` or the real category folders.
"""

import os
import shutil
import sys
import tempfile
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PLUGIN_SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QGIS_PREFIX = os.environ.get("QGIS_PREFIX_PATH", r"D:\QGIS3.34.1\apps\qgis")

CHECKS = []


def check(name, condition, detail=""):
    ok = bool(condition)
    CHECKS.append((name, ok, detail))
    print(("PASS  " if ok else "FAIL  ") + name + ((" | " + detail) if detail else ""))
    return ok


class FakeMessageBar:
    def __init__(self):
        self.messages = []

    def pushMessage(self, *args, **kwargs):
        self.messages.append(args)


class DummyIface:
    def __init__(self, window):
        self._window = window
        self.bar = FakeMessageBar()

    def mainWindow(self):
        return self._window

    def messageBar(self):
        return self.bar

    def addPluginToMenu(self, *args):
        pass

    def removePluginMenu(self, *args):
        pass

    def addToolBarIcon(self, *args):
        pass

    def removeToolBarIcon(self, *args):
        pass

    def addDockWidget(self, *args):
        pass

    def removeDockWidget(self, *args):
        pass

    def activeLayer(self):
        return None

    def mapCanvas(self):
        return None


def copy_plugin():
    target = os.path.join(tempfile.mkdtemp(prefix="pro_toolbox_test_"), "pro_toolbox")
    ignore = shutil.ignore_patterns(
        ".git", "__pycache__", "dist", "docs", "assets", "*.pyc", "*.zip",
        "libs", "tests", "symbology-style.db",
    )
    shutil.copytree(PLUGIN_SRC, target, ignore=ignore)
    return target


def tab_is_populated(tab_widget):
    layout = tab_widget.layout()
    return layout is not None and layout.count() > 0


def main():
    from qgis.core import QgsApplication
    from qgis.PyQt.QtWidgets import QMainWindow

    QgsApplication.setPrefixPath(QGIS_PREFIX, True)
    app = QgsApplication([], False)
    app.initQgis()

    tmp_plugin = None
    plugin = None
    try:
        tmp_plugin = copy_plugin()
        sys.path.insert(0, tmp_plugin)

        import main as plugin_main

        window = QMainWindow()
        iface = DummyIface(window)
        plugin = plugin_main.ProToolboxPlugin(iface)
        plugin.build_ui()

        titles = [a.title for a in plugin.loaded_addons]
        print("titles:", titles)

        check("8 addon classes load", len(plugin.loaded_addons) == 8, f"got {len(plugin.loaded_addons)}")
        check("8 tabs mounted", plugin.tabs.count() == 8, f"got {plugin.tabs.count()}")
        check("every tab has a non-empty UI",
              all(tab_is_populated(plugin.tabs.widget(i)) for i in range(plugin.tabs.count())))
        check("pinned core module mounts first", titles and "自动存档" in titles[0] or "Autosave" in (titles[0] if titles else ""))
        check("AI studio mounts last", bool(titles) and ("模块工坊" in titles[-1] or "Module Studio" in titles[-1]))
        check("no loader warnings", not iface.bar.messages, str(iface.bar.messages[:3]))

        config_path = os.path.join(tmp_plugin, "addons", "workspace_config.json")
        check("workspace config persisted", os.path.exists(config_path))
        check("default category folders created",
              all(os.path.isdir(os.path.join(tmp_plugin, "addons", name))
                  for name in plugin_main.DEFAULT_CATEGORY_FOLDERS))

        plugin.on_language_changed(1)
        zh_titles = [a.title for a in plugin.loaded_addons]
        check("Chinese switch keeps 8 tabs", len(plugin.loaded_addons) == 8, str(zh_titles[:3]))
        check("Chinese titles applied", any("自动存档" in t for t in zh_titles), str(zh_titles[:3]))
        plugin.on_language_changed(0)
        en_titles = [a.title for a in plugin.loaded_addons]
        check("English switch restores titles", any("Autosave" in t for t in en_titles), str(en_titles[:3]))

        # The manager organizes modules by physically moving the file into a
        # category sub-folder; simulate that and verify the bookmark view.
        cat_dir = os.path.join(tmp_plugin, "addons", "02_遥感影像处理")
        os.makedirs(cat_dir, exist_ok=True)
        src_05 = os.path.join(tmp_plugin, "addons", "05_excel_map.py")
        dst_05 = os.path.join(cat_dir, "05_excel_map.py")
        shutil.move(src_05, dst_05)
        plugin.config["active_nav"] = "cat:02_遥感影像处理"
        plugin.load_all_addons()
        cat_titles = [a.title for a in plugin.loaded_addons]
        check("category view keeps the moved module", any("表格转点" in t or "Table to Points" in t for t in cat_titles), str(cat_titles))
        check("category view keeps pinned modules", any("自动存档" in t or "Autosave" in t for t in cat_titles))
        check("category view hides modules from other folders", not any("影像去黑边" in t or "Raster NoData" in t for t in cat_titles))
        shutil.move(dst_05, src_05)

        plugin.config["active_nav"] = "ws:🌟 全部模块 (All)"
        plugin.save_config()
        plugin.load_all_addons()

        # A new module dropped into a category folder must be discovered on rescan.
        extra = os.path.join(tmp_plugin, "addons", "02_遥感影像处理", "08_test_probe.py")
        with open(extra, "w", encoding="utf-8") as fh:
            fh.write(
                "from base_addon import BaseAddon, tr\n"
                "\n"
                "class ProbeAddon(BaseAddon):\n"
                "    order = 8\n"
                "    title = tr(\"🧪 探针\", \"🧪 Probe\")\n"
                "    def setup_ui(self, parent_widget):\n"
                "        from qgis.PyQt.QtWidgets import QLabel, QVBoxLayout\n"
                "        QVBoxLayout(parent_widget).addWidget(QLabel(\"probe\"))\n"
            )
        plugin.load_all_addons()
        probe_titles = [a.title for a in plugin.loaded_addons]
        check("sub-folder module discovered on rescan", len(plugin.loaded_addons) == 9, str(probe_titles))
        check("sub-folder module UI built", any("探针" in t or "Probe" in t for t in probe_titles))
        os.remove(extra)
        plugin.load_all_addons()

        # Persistence across instances.
        plugin2 = plugin_main.ProToolboxPlugin(DummyIface(QMainWindow()))
        check("pinned modules survive restart", "01_auto_save.py" in plugin2.config["pinned_modules"])
        check("active workspace survives restart", plugin2.config["active_workspace"] == "🌟 全部模块 (All)",
              str(plugin2.config["active_workspace"]))

        if plugin is not None:
            plugin.unload_all_addons()
    except Exception:
        traceback.print_exc()
        check("suite completed without exception", False)
    finally:
        try:
            if plugin is not None:
                plugin.unload()
        except Exception:
            pass
        app.exitQgis()
        if tmp_plugin and os.path.isdir(tmp_plugin):
            shutil.rmtree(os.path.dirname(tmp_plugin), ignore_errors=True)

    failed = [name for name, ok, _ in CHECKS if not ok]
    print("\n%d checks, %d failed" % (len(CHECKS), len(failed)))
    if failed:
        print("FAILED:", failed)
        print("RESULT: FAIL")
        sys.stdout.flush()
        os._exit(1)
    print("RESULT: PASS")
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    sys.exit(main())
