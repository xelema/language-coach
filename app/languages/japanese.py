"""Paquet japonais : tout ce qui est propre au japonais vit ici."""
from .base import Language, Register

LANGUAGE = Language(
    code="ja",
    name="japonais",
    native_name="日本語",
    # Hiragana, katakana, kanji et katakana demi-largeur : ce qui doit être
    # cliquable pour être entendu.
    script=r"[\u3040-\u309F\u30A0-\u30FF\u3400-\u4DBF\u4E00-\u9FFF\uFF66-\uFF9D]",
    tts_language="ja",
    # Aucune voix épinglée : la première voix japonaise active est résolue via
    # l'API Cartesia, puis modifiable dans les réglages.
    tts_voice=None,
    tts_voice_hint="",
    registers=(
        Register("familier", "タメ口 (casual)", "forme neutre entre proches, sans です/ます"),
        Register("neutre", "neutre écrit", "だ / である : récits, notes, titres"),
        Register("poli", "です・ます (poli)", "registre par défaut avec un inconnu ou un aîné"),
        Register("honorifique", "敬語 (keigo)", "尊敬語 / 謙譲語 : reconnaissance, pas priorité"),
    ),
    ime={
        "windows": ("Paramètres → Heure et langue → Langue et région → ajouter Japonais "
                    "(Microsoft IME). Win+Espace change de disposition, 半角/全角 passe en "
                    "saisie kana ; Alt+~ bascule romaji/kana. Le clavier visuel montre les caractères."),
        "android": ("Gboard → Paramètres → Langues → Ajouter un clavier → Japonais : disposition "
                    "12 touches (かな) ou QWERTY avec saisie romaji ; barre d'espace maintenue "
                    "pour changer de langue."),
        "note": ("En saisie romaji, taper la prononciation (nihongo) puis choisir le kanji dans la "
                 "barre de conversion : la lecture ne se devine pas depuis l'écriture."),
    },
    listening_queries=(
        "japonais débutant compréhension orale dialogue lent",
        "japanese slow listening practice beginner conversation",
        "日本語 聞き取り 初級 ゆっくり 会話",
    ),
    resources=(
        {"name": "Jisho (dictionnaire japonais-anglais, entrées et lectures vérifiables)",
         "url": "https://jisho.org/", "note": "vérifier la lecture et le niveau d'usage avant d'enseigner"},
        {"name": "NHK NEWS WEB EASY (actualités réécrites en japonais simple, audio)",
         "url": "https://www3.nhk.or.jp/news/easy/",
         "note": "textes adaptés et lus : utile pour l'écoute réelle sans matériel fait maison"},
    ),
    coaching_notes=(
        "Trois écritures cohabitent : hiragana pour la grammaire, katakana pour les emprunts, "
        "kanji pour le sens. Ne pas tout écrire en romaji, et ne jamais remplacer un kanji par sa "
        "lecture sans le dire.",
        "Le japonais se compte en mores (durées), pas en syllabes : les voyelles longues et le っ "
        "changent le mot. Travailler le rythme, pas seulement les sons.",
        "L'accent de hauteur (pitch accent) distingue des mots homophones : le signaler à l'écoute "
        "quand c'est le cas, sans en faire un cours de phonétique.",
        "Le japonais n'a pas d'espaces : la segmentation en mots n'est pas visible à l'écrit, donc "
        "ne pas bâtir un exercice sur « compter les mots ».",
        "Registre : です・ます par défaut avec un inconnu ou un aîné, タメ口 avec un proche ; "
        "l'honorifique se reconnaît avant de se produire. Les particules (は / が, を, に, で) "
        "portent la fonction, pas l'ordre des mots.",
    ),
)
