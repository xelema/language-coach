# language-coach

Coach de langue auto-hébergé : un agent de conversation qui enseigne, fait
pratiquer, corrige et tient la progression. Choisi une fois au démarrage — la
langue (japonais, coréen), l'objectif, le niveau déjà connu — puis il s'y
adapte séance après séance.

## Lancer

```bash
./run.sh                 # http://127.0.0.1:51121
```

Le premier lancement crée le venv et installe les dépendances. Au tout premier
accès, l'application demande la langue, l'objectif, le niveau et l'accès audio :
c'est cette initialisation qui remplace tout réglage à la main.

## Ce qu'il faut fournir

1. **L'accès au modèle** : une connexion Google (`/oauth/login`) pour Gemini via
   l'abonnement Antigravity — aucune clé API. Alternative : `LC_PROVIDER=opencode`
   avec `OPENCODE_API_KEY`.
2. **La voix** : `CARTESIA_API_KEY` pour que le texte de la langue cible soit
   audible (cliquable dans le fil, vitesse normale ou lente). Sans clé, le reste
   fonctionne, seuls les extraits audio manquent.
3. **Le mot de passe du site** : `LC_PASSWORD_HASH` (`python -m app.auth`), pour
   que l'app ne soit pas ouverte à qui passe.

Voir `.env.example` pour le détail des variables.

## Développement

```bash
.venv/bin/python -m app.main       # serveur de dev
.venv/bin/python -m unittest discover -s tests
node tests/prefill.test.mjs        # logique de saisie de l'interface
```

## Ajouter une langue

Un fichier suffit : `app/languages/<code>.py` qui expose une variable
`LANGUAGE` (voir `app/languages/japanese.py`). Le paquet déclare ce qui est
propre à la langue — écriture cible, voix de synthèse, registres, aide à la
saisie, ressources, points de vigilance pédagogiques. Le reste de
l'application ne connaît aucune langue : le formulaire d'initialisation, les
schémas d'outils du coach et les prompts se remplissent à partir du paquet.

Le paquet est découvert automatiquement au démarrage : ni la liste des langues
ni les gabarits de `coach/` ne sont à modifier.

## Architecture

- `app/main.py` — FastAPI : session, fils de discussion, tour de chat en NDJSON,
  audio, TTS, Anki, progression, profil.
- `app/coach.py` — le coach : prompt système assemblé à chaque tour, quatre
  outils (`save_progress`, `request_recording`, `hear_recording`,
  `set_channels`), boucle d'appels d'outils, chronomètre.
- `app/notebook.py` — le carnet : progression append-only, validation stricte,
  profil, calibrage, révisions locales.
- `app/languages/` — les paquets de langue.
- `coach/*.md` — les gabarits du prompt (protocole, niveaux, ressources), avec
  des variables `{{...}}` remplies par `app/prompts.py`.
- `app/gemini.py` / `app/opencode.py` — les fournisseurs de modèle.
- `app/anki.py` — export `.apkg` des cartes.

Détail de la reprise du projet d'origine : `docs/refonte-plan.md`.
