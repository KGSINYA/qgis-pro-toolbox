# -*- coding: utf-8 -*-
"""Extremely small runtime translator for Pro Toolbox (no .ts/.qm build step).

Every user-visible string is declared as a pair::

    from base_addon import tr
    btn = QPushButton(tr("<zh text>", "<en text>"))

``tr()`` returns the Chinese or English half depending on the language that is
currently active.  The language itself is resolved once, in this order:

1. the user's saved choice (``ProToolbox/language`` in QgsSettings),
2. QGIS' own UI locale (``locale/userLocale``, e.g. ``zh_CN``),
3. English.

Switching language does not translate existing widgets; ``main.py`` rebuilds
the addon tabs after calling :func:`set_language`, which re-executes every
addon module so all ``title`` attributes and ``setup_ui()`` strings are
re-evaluated in the new language.
"""

LANG_EN = "en"
LANG_ZH = "zh"
SUPPORTED = (LANG_EN, LANG_ZH)

# QgsSettings keys (QgsSettings is a QSettings subclass, so the same API works).
SETTINGS_KEY = "ProToolbox/language"
LOCALE_KEY = "locale/userLocale"

# Resolved lazily on first use, then cached for the whole QGIS session.
_current = None


def _settings():
    """Return a QgsSettings instance, or None when running outside QGIS."""
    try:
        from qgis.core import QgsSettings
        return QgsSettings()
    except Exception:
        return None


def normalize(lang):
    """Map anything language-like (``zh_CN``, ``ZH``, ``zh-Hans``) to ``zh``/``en``."""
    lang = str(lang or "").strip().lower().replace("-", "_")
    return LANG_ZH if lang.startswith("zh") else LANG_EN


def detect_language():
    """Pick the startup language: saved choice > QGIS locale > English."""
    settings = _settings()
    if settings is not None:
        try:
            saved = str(settings.value(SETTINGS_KEY, "") or "").strip().lower()
            if saved in SUPPORTED:
                return saved
            locale = str(settings.value(LOCALE_KEY, "") or "").strip()
            if locale:
                return normalize(locale)
        except Exception:
            pass
    return LANG_EN


def current_language():
    """Return ``zh`` or ``en``; detected on first call."""
    global _current
    if _current is None:
        _current = detect_language()
    return _current


def set_language(lang, persist=True):
    """Activate ``lang``.  Returns True only when the language actually changed.

    ``persist=False`` is handy for tests or transient previews.
    """
    global _current
    new_lang = normalize(lang)
    changed = new_lang != current_language()
    _current = new_lang

    if persist:
        settings = _settings()
        if settings is not None:
            try:
                settings.setValue(SETTINGS_KEY, new_lang)
            except Exception:
                pass
    return changed


def language_label():
    """Native label for the toolbar selector (never translated)."""
    return "🌐 中文" if current_language() == LANG_ZH else "🌐 English"


def tr(zh, en):
    """Return the string for the active language.

    Both arguments are plain strings; f-strings are fine because they are
    evaluated before the call::

        tr(f"<zh text>: {n}", f"<en text>: {n}")
    """
    return zh if current_language() == LANG_ZH else en
