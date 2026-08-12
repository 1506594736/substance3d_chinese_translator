# -*- coding: utf-8 -*-
"""Painter entry shim for the unified SP/SD Chinese translation plug-in.

Substance 3D Painter loads this package from ``python/plugins`` and calls
``start_plugin()`` / ``close_plugin()``.  Substance 3D Designer loads the
nested ``substance3d_chinese_translator`` module directly through
``pluginInfo.json``, so this file stays a tiny, Painter-only shim and is never
executed there.
"""


def start_plugin():
    from . import substance3d_chinese_translator as _impl
    _impl.start_plugin()


def close_plugin():
    from . import substance3d_chinese_translator as _impl
    _impl.close_plugin()


def reload_plugin():
    from . import substance3d_chinese_translator as _impl
    if hasattr(_impl, "reload_plugin"):
        _impl.reload_plugin()
