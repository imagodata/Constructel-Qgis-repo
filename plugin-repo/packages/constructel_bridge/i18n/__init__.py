# -*- coding: utf-8 -*-
"""
Constructel Bridge — Systeme de traduction leger.

Detecte la langue depuis:
  1. Setting constructel_bridge/language (surcharge manuelle)
  2. Locale QGIS (QgsSettings locale/userLocale)
  3. Locale systeme (QLocale)

Langues supportees: fr, en, pt
Fallback: en
"""

import locale as _locale

from qgis.core import QgsSettings
from qgis.PyQt.QtCore import QLocale

from .translations import TRANSLATIONS

SUPPORTED_LANGUAGES = ("fr", "en", "pt")
_DEFAULT_LANG = "en"
_current_lang: str = _DEFAULT_LANG


def detect_language() -> str:
    """Detecte la langue a utiliser (code 2 lettres)."""
    settings = QgsSettings()

    # 1. Surcharge manuelle du plugin
    forced = settings.value("constructel_bridge/language", "")
    if forced and forced in SUPPORTED_LANGUAGES:
        return forced

    # 2. Locale QGIS
    qgis_locale = settings.value("locale/userLocale", "")
    if qgis_locale:
        lang = qgis_locale[:2].lower()
        if lang in SUPPORTED_LANGUAGES:
            return lang

    # 3. Locale systeme via Qt
    qt_lang = QLocale.system().name()[:2].lower()
    if qt_lang in SUPPORTED_LANGUAGES:
        return qt_lang

    # 4. Locale systeme via Python
    try:
        py_lang = _locale.getdefaultlocale()[0]
        if py_lang:
            lang = py_lang[:2].lower()
            if lang in SUPPORTED_LANGUAGES:
                return lang
    except Exception:
        pass

    return _DEFAULT_LANG


def init_language():
    """Initialise la langue au demarrage du plugin."""
    global _current_lang
    _current_lang = detect_language()


def get_language() -> str:
    """Retourne le code de langue actif."""
    return _current_lang


def set_language(lang: str):
    """Force une langue (persistee dans les settings)."""
    global _current_lang
    if lang in SUPPORTED_LANGUAGES:
        _current_lang = lang
        QgsSettings().setValue("constructel_bridge/language", lang)


def tr(key: str, **kwargs) -> str:
    """Traduit une cle.

    Args:
        key: Cle de traduction (ex: "menu.connect")
        **kwargs: Variables de substitution (ex: user="John")

    Returns:
        Chaine traduite, ou la cle elle-meme si introuvable.
    """
    lang_dict = TRANSLATIONS.get(_current_lang, TRANSLATIONS[_DEFAULT_LANG])
    text = lang_dict.get(key)
    if text is None:
        # Fallback vers anglais
        text = TRANSLATIONS[_DEFAULT_LANG].get(key, key)
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, IndexError):
            pass
    return text
