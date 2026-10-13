"""Registre des langues disponibles.

Chaque module de ce dossier qui expose une variable `LANGUAGE` est découvert
au premier appel. Pour ajouter une langue : copier un paquet existant, changer
les valeurs, c'est tout.
"""
import importlib
import pkgutil

from .base import CEFR, Language, Level, Register

_registry: dict[str, Language] | None = None


def _discover() -> dict[str, Language]:
    found: dict[str, Language] = {}
    for module in pkgutil.iter_modules(__path__):
        name = module.name
        if name.startswith("_") or name in ("base",):
            continue
        mod = importlib.import_module(f"{__name__}.{name}")
        language = getattr(mod, "LANGUAGE", None)
        if isinstance(language, Language):
            found[language.code] = language
    return dict(sorted(found.items()))


def all() -> dict[str, Language]:
    global _registry
    if _registry is None:
        _registry = _discover()
    return _registry


def get(code: str) -> Language:
    """La langue demandée, ou une erreur explicite listant celles connues."""
    language = all().get((code or "").strip().lower())
    if language is None:
        known = ", ".join(all()) or "aucune"
        raise ValueError(f"Langue inconnue : {code!r} (disponibles : {known}).")
    return language


def has(code: str) -> bool:
    return (code or "").strip().lower() in all()


def codes() -> tuple[str, ...]:
    return tuple(all())


def catalog() -> list[dict]:
    """Ce que l'interface affiche à l'initialisation et dans les réglages."""
    return [{"code": lang.code, "name": lang.name, "native_name": lang.native_name,
             "registers": [{"id": r.id, "label": r.label, "note": r.note} for r in lang.registers],
             "levels": [{"code": lv.code, "label": lv.label, "can": lv.can} for lv in lang.levels]}
            for lang in all().values()]


__all__ = ["CEFR", "Language", "Level", "Register", "all", "catalog", "codes", "get", "has"]
