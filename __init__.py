# -*- coding: utf-8 -*-

def classFactory(iface):

    from .main import ProToolboxPlugin
    return ProToolboxPlugin(iface)