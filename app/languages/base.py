"""Ce qu'un « language pack » doit fournir — et rien de plus.

Ajouter une langue = créer `app/languages/<code>.py` et y définir une instance
`Language`. Le paquet est découvert automatiquement au démarrage
(`app/languages/__init__.py`), donc aucun autre fichier n'est à modifier.

Tout ce qui est vraiment propre à une langue vit ici : l'écriture cible (pour
savoir quel texte est « audible »), la voix de synthèse, les registres, les
requêtes de recherche vidéo, les ressources et les points de vigilance
pédagogiques. Le reste de l'application ne connaît aucune langue.
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Register:
    """Un registre de langue utilisable dans une carte ou un exercice."""
    id: str
    label: str
    note: str = ""


@dataclass(frozen=True)
class Level:
    """Un palier de niveau déjà connu, déclarable à l'initialisation."""
    code: str
    label: str
    can: str


# Échelle commune à toutes les langues : l'initialisation demande où se situe
# l'apprenant, le paquet n'a qu'à la reprendre ou à la préciser s'il le souhaite.
CEFR: tuple[Level, ...] = (
    Level("A0", "Débutant complet", "aucune base : ni alphabet, ni phrases"),
    Level("A1.0", "Faux débutant", "quelques mots et formules, écriture encore hésitante"),
    Level("A1", "Élémentaire", "se présenter, questions et réponses très simples à l'écrit comme à l'oral"),
    Level("A2", "Pré-intermédiaire", "phrases simples sur la vie quotidienne, échanges courts suivis"),
    Level("B1", "Intermédiaire", "raconter, donner son avis, comprendre un échange courant"),
    Level("B2", "Avancé", "discuter d'un sujet abstrait, comprendre des locuteurs natifs à débit normal"),
)


@dataclass(frozen=True)
class Language:
    """Une langue enseignable, décrite une fois pour toute l'application."""
    code: str                      # ISO 639-1 : "ja", "ko"
    name: str                      # nom français : "japonais"
    native_name: str               # nom dans la langue : "日本語"
    script: str                    # écriture cible, pour repérer le texte audible
    # Synthèse vocale (Cartesia). tts_voice épingle une voix ; sinon la
    # première voix disponible de la langue est résolue puis mémorisée dans
    # les réglages, où l'apprenant peut en choisir une autre.
    tts_language: str = ""
    tts_voice: str | None = None
    tts_voice_hint: str = ""       # "feminine" | "masculine" | "" (indifférent)
    registers: tuple[Register, ...] = ()
    ime: dict[str, str] = field(default_factory=dict)
    listening_queries: tuple[str, ...] = ()
    resources: tuple[dict[str, str], ...] = ()
    coaching_notes: tuple[str, ...] = ()

    def register(self, register_id: str) -> Register | None:
        return next((r for r in self.registers if r.id == register_id), None)

    @property
    def register_ids(self) -> tuple[str, ...]:
        return tuple(r.id for r in self.registers)

    @property
    def default_register(self) -> str:
        ids = self.register_ids
        return "neutre" if "neutre" in ids else (ids[0] if ids else "")

    @property
    def levels(self) -> tuple[Level, ...]:
        return CEFR

    def level(self, code: str) -> Level | None:
        return next((level for level in self.levels if level.code == code), None)
