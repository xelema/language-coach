"""Export .apkg des cartes du carnet, construit à chaque téléchargement.

Les identifiants de modèle, de paquet et de note sont dérivés de la langue et
du nom de l'apprenant : ils restent stables d'un export à l'autre, donc
réimporter met à jour les notes au lieu de les dupliquer. Les paquets sont
régénérés sous `data/anki/` et servis directement par l'API.
"""
import csv
from datetime import date
import hashlib
import html
import io
import re

import genanki

from . import languages
from .auth import data_dir

FIELDS = ("ID", "Question", "Reponse", "Registre", "Source", "Date", "Competence")
NOTE_TYPE = "Coach de langue"


def context(state) -> tuple[languages.Language, str]:
    """Langue du carnet et identifiant stable de l'apprenant (nom ou défaut)."""
    language = languages.get(state.get("language") or "")
    name = ((state.get("profile") or {}).get("name") or "").strip()
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "apprenant"
    return language, slug


def _ids(language, slug: str) -> tuple[int, int]:
    """IDs stables et propres à (langue, apprenant) : Anki s'en sert pour
    reconnaître un modèle et un paquet déjà importés."""
    digest = hashlib.sha1(f"{language.code}|{slug}".encode()).hexdigest()
    model = int(digest[:8], 16) % 10**9 + 10**9
    return model, model + 1


def name_pattern(code: str) -> str:
    return rf"{code}-(tout|\d{{4}}-\d{{2}}-\d{{2}})\.apkg"


def _html(value):
    # Les données sont du texte, jamais du HTML ou des commandes média Anki.
    return (html.escape(value).replace("[", "&#91;").replace("\r\n", "\n")
            .replace("\r", "\n").replace("\n", "<br>").replace("\t", "&#9;"))


def _tag(value):
    return re.sub(r"[^\w-]", "_", value)


def render_tsv(cards, day=None, *, language, learner="apprenant"):
    """Retourne (texte UTF-8, nombre de notes, IDs audio exclus).

    day filtre la date d'introduction. ID stable indépendamment du contenu.
    Une seule carte par note ; aucun verso automatique ambigu.
    """
    if day is not None:
        if date.fromisoformat(day).isoformat() != day:
            raise ValueError("Date attendue AAAA-MM-JJ")
    seen = set()
    validated = []
    for card in cards:
        for field in ("id", "prompt", "answer", "register", "source", "introduced", "skill"):
            if not isinstance(card.get(field), str) or not card[field].strip():
                raise ValueError(f"Carte : champ texte manquant ou vide : {field}")
            if any(ord(c) < 32 and c not in "\t\r\n" for c in card[field]):
                raise ValueError(f"Caractère de contrôle interdit : {field}")
        if card["id"] != card["id"].strip() or any(c in card["id"] for c in "\t\r\n"):
            raise ValueError("ID invalide")
        if card["id"] in seen:
            raise ValueError(f"ID dupliqué : {card['id']}")
        seen.add(card["id"])
        if date.fromisoformat(card["introduced"]).isoformat() != card["introduced"]:
            raise ValueError("Date d'introduction attendue AAAA-MM-JJ")
        validated.append(card)

    prefix = f"{language.code}-{learner}::"
    deck = deck_name(language)
    output = io.StringIO(newline="")
    output.write(f"#separator:Tab\n#html:true\n#notetype:{NOTE_TYPE}\n#deck:{deck}\n")
    output.write("#tags column:8\n#columns:" + "\t".join((*FIELDS, "Tags")) + "\n")
    writer = csv.writer(output, delimiter="\t", lineterminator="\n")
    count, skipped = 0, []
    for card in sorted(validated, key=lambda c: (c["introduced"], c["id"])):
        if day is not None and card["introduced"] != day:
            continue
        if card["skill"] == "ecoute":
            # ponytail: export texte seulement ; ajouter médias vérifiés si nécessaire.
            skipped.append(card["id"])
            continue
        tags = " ".join((f"coach_{language.code}", "jour::" + card["introduced"],
                         "registre::" + _tag(card["register"]),
                         "competence::" + _tag(card["skill"])))
        values = (prefix + card["id"], card["prompt"], card["answer"],
                  card["register"], card["source"], card["introduced"], card["skill"])
        writer.writerow([*map(_html, values), tags])
        count += 1
    return output.getvalue(), count, skipped


def deck_name(language) -> str:
    return f"{NOTE_TYPE}::{language.name.capitalize()}"


def _write_apkg(tsv, path, *, language, learner="apprenant"):
    model_id, deck_id = _ids(language, learner)
    model = genanki.Model(model_id, NOTE_TYPE,
        fields=[{"name": name} for name in FIELDS], sort_field_index=1,
        templates=[{"name": "Rappel", "qfmt": "{{Question}}",
            "afmt": '{{FrontSide}}<hr id="answer">'
                    f'<div lang="{language.code}" class="target">{{Reponse}}</div>'
                    '<p class="meta">{{Registre}} · {{Competence}}</p>'
                    '<details><summary>Source</summary>{{Source}}<br>{{Date}}</details>'}],
        css=".card { font: 22px sans-serif; text-align: center; line-height: 1.5; }"
            ".target { font-size: 32px; } .meta, details { font-size: 15px; }")
    deck = genanki.Deck(deck_id, deck_name(language))
    lines = (line for line in tsv.splitlines() if not line.startswith("#"))
    for row in csv.reader(lines, delimiter="\t"):
        # Le GUID dépend uniquement de (langue, apprenant, ID), jamais du texte corrigible.
        deck.add_note(genanki.Note(model=model, fields=row[:7], tags=row[7].split(),
                                  guid=genanki.guid_for(row[0])))
    temporary = path.with_name(path.name + ".tmp")
    genanki.Package(deck).write_to_file(str(temporary))
    temporary.replace(path)


def package_list(state):
    """Un paquet cumulatif, puis un par jour ayant introduit des cartes
    exportables (un jour de cartes d'écoute seulement n'en produit aucun)."""
    language, learner = context(state)
    result = [{"name": f"{language.code}-tout.apkg", "day": None,
               "count": render_tsv(state["cards"], language=language, learner=learner)[1]}]
    for day in sorted({c["introduced"] for c in state["cards"]}):
        count = render_tsv(state["cards"], day, language=language, learner=learner)[1]
        if count:
            result.append({"name": f"{language.code}-{day}.apkg", "day": day, "count": count})
    return result


def build(state, name):
    """Régénère data/anki/<name> depuis le carnet ; renvoie (chemin, nombre)."""
    language, learner = context(state)
    match = re.fullmatch(name_pattern(language.code), name)
    if not match:
        raise ValueError("Paquet inconnu.")
    day = None if match.group(1) == "tout" else match.group(1)
    tsv, count, _skipped = render_tsv(state["cards"], day, language=language, learner=learner)
    if day is not None and count == 0:
        raise ValueError("Aucune carte exportable ce jour-là.")
    out = data_dir() / "anki"
    out.mkdir(parents=True, exist_ok=True)
    path = out / name
    _write_apkg(tsv, path, language=language, learner=learner)
    return path, count
