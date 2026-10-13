# language-coach

Coach de langue auto-hébergé : un agent de conversation qui enseigne, fait
pratiquer, corrige et tient la progression. Vous choisissez une fois — la langue
(japonais, coréen), l'objectif, le niveau déjà connu — puis il s'y adapte séance
après séance, y compris en réglant lui-même la difficulté.

Mise en route détaillée : **[QUICKSTART.md](QUICKSTART.md)**.

## Démarrage rapide

```bash
git clone https://github.com/xelema/language-coach.git
cd language-coach
./run.sh                 # http://127.0.0.1:51121
```

1. **Générer le mot de passe du site** (sans lui, la page de connexion refuse
   tout le monde) puis le coller dans un `.env` à côté de `run.sh` :
   ```bash
   .venv/bin/python -m app.auth     # → LC_PASSWORD_HASH=scrypt$...
   ```
2. **Ouvrir `http://127.0.0.1:51121`**, se connecter, puis cliquer sur
   **Connexion Google** (`/oauth/login`) : c'est le chemin d'accès au modèle
   Gemini, via l'abonnement Antigravity, sans clé API. Le jeton reste dans
   `data/`, il ne part jamais dans le navigateur.
3. **`CARTESIA_API_KEY` dans `.env`** pour que le texte de la langue cible soit
   audible, puis choisir la voix dans les Paramètres du site.
4. **Suivre la mise en route** (`/onboarding`) : langue, objectif, niveau,
   cadence, échéance éventuelle, accès audio, et — si vous le souhaitez — des
   vidéos d'écoute issues d'une vraie recherche.

Le port **51121** n'est pas un détail : la redirection OAuth de Google est
enregistrée dessus. Changer de port oblige à refaire la connexion Google.

### Ce qui dégrade quoi

- Sans **mot de passe** : personne n'entre.
- Sans **connexion Google** (ou sans `LC_PROVIDER=opencode` +
  `OPENCODE_API_KEY`) : l'interface répond, mais aucune séance ne démarre.
- Sans **clé Cartesia** : tout fonctionne, sauf le son — le texte de la langue
  cible n'est plus cliquable-pour-entendre.
- Sans **`yt-dlp`** ou si YouTube refuse : seule la recherche de vidéos échoue,
  avec son message ; le reste de la mise en route continue.
- Sans **échéance** : c'est le mode par défaut. Le coach peut en proposer une,
  vous pouvez en poser une (et la retirer) dans les Paramètres.

Voir `.env.example` pour toutes les variables.

## Utilisation

- **Séance** : menu ☰ → *Commencer une séance*. Un exercice à la fois, un
  chronomètre serveur, un bouton micro, et tout texte de la langue cible
  cliquable pour l'entendre (normal ou lent). Le fil « ? » permet de poser une
  question sans quitter la séance.
- **Clôture** : le bouton ■ demande le ressenti (*trop facile / juste bien /
  trop dur*, ou rien). Le coach l'enregistre tel quel avec son auto-critique et
  **le seul réglage** prévu pour la séance suivante ; le fil affiche ce
  calibrage, que vous pouvez contester.
- **Progression** : profil, rangs, minutes, calendrier des jours travaillés,
  calibrage, vidéos validées, prises audio.
- **Cartes Anki** : les `.apkg` sont régénérés à chaque téléchargement et
  s'importent dans AnkiDroid ; Anki reste alors le seul ordonnanceur.

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
  audio, TTS, Anki, progression, profil, mise en route.
- `app/coach.py` — le coach : prompt système assemblé à chaque tour, quatre
  outils (`save_progress`, `request_recording`, `hear_recording`,
  `set_channels`), boucle d'appels d'outils, chronomètre.
- `app/notebook.py` — le carnet : progression append-only, validation stricte,
  profil, calibrage, ressources validées, révisions locales.
- `app/languages/` — les paquets de langue.
- `coach/*.md` — les gabarits du prompt (protocole, niveaux, ressources), avec
  des variables `{{...}}` remplies par `app/prompts.py`.
- `app/gemini.py` / `app/opencode.py` — les fournisseurs de modèle.
- `app/anki.py` — export `.apkg` des cartes.

Détail de la reprise du projet d'origine : `docs/refonte-plan.md`.
