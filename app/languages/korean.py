"""Paquet coréen : tout ce qui est propre au coréen vit ici."""
from .base import Language, Register

LANGUAGE = Language(
    code="ko",
    name="coréen",
    native_name="한국어",
    # Syllabes hangul précomposées, jamos et demi-largeur : c'est ce qui doit
    # être cliquable pour être entendu.
    script=r"[\u1100-\u11FF\u3130-\u318F\uAC00-\uD7AF]",
    tts_language="ko",
    # Voix coréenne choisie au banc d'essai d'origine ; remplaçable depuis les
    # réglages du site.
    tts_voice="9626c31c-bec5-4cca-baa8-f8ba9e84c8bc",
    registers=(
        Register("familier", "banmal (반말)", "tutoiement entre proches du même âge ou plus jeunes"),
        Register("neutre", "neutre", "sans marqueur de politesse : style écrit, titres"),
        Register("poli", "poli courant (-요)", "해요체 : registre par défaut avec un adulte inconnu"),
        Register("honorifique", "honorifique", "습니다체 et 높임말 : reconnaissance, pas priorité"),
    ),
    ime={
        "windows": ("Paramètres → Heure et langue → Langue et région → ajouter Coréen "
                    "(Microsoft IME). Win+Espace change de disposition, A/가 passe en hangeul. "
                    "Le clavier visuel Windows montre les caractères."),
        "android": ("Gboard → Paramètres → Langues → Ajouter un clavier → Coréen, disposition "
                    "complète 두벌식/QWERTY ; barre d'espace maintenue pour changer de langue."),
        "note": ("Les tutoriels illustrent un QWERTY : apprendre les positions, pas les lettres "
                 "latines imprimées sur un AZERTY."),
    },
    listening_queries=(
        "coréen débutant dialogue lent compréhension orale",
        "korean slow listening practice beginner conversation",
        "초급 한국어 듣기 쉬운 대화",
    ),
    resources=(
        {"name": "Nuri Sejong (manuels et audios institutionnels, gratuits)",
         "url": "https://nuri.iksi.or.kr/", "note": "certains accès demandent un compte gratuit"},
        {"name": "Dictionnaire d'apprentissage coréen-français (NIKL)",
         "url": "https://krdict.korean.go.kr/fra/mainAction?flag=PC",
         "note": "sens, exemples et prononciations à vérifier avant d'enseigner"},
    ),
    coaching_notes=(
        "Le banmal n'est pas de l'argot : c'est un registre relationnel. Identifier l'interlocuteur "
        "et l'intention avant d'enseigner une forme, jamais une transformation universelle « enlever 요 ».",
        "Pas de romanisation par défaut : expliquer un son par la position de la bouche et le rythme.",
        "Distinguer incorrect / acceptable mais moins naturel / variante correcte ; les particules "
        "omises peuvent être naturelles à l'oral.",
        "Le coréen s'écrit en blocs syllabiques : la saisie se compose (ㅎ + ㅏ + ㄴ → 한).",
    ),
)
