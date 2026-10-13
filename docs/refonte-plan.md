# Refonte `language-coach` — reconnaissance et plan

Source de référence (clone lecture seule, **jamais modifié**) :
`~/sites/lab/_ref/korean-coach-ref` = `xelema/korean-coach` (privé, branche
`main`, dernier push 2026-10-05, 176 fichiers suivis, 2,1 Mo).

Nouveau projet : `~/sites/lab/language-coach` (ce dépôt), destiné à
`xelema/language-coach`.

---

## 1. Ce que fait korean-coach (architecture actuelle)

FastAPI mono-process, `uvicorn` sur `127.0.0.1:51121`, données dans
`KC_DATA_DIR` (SQLite `coach.db` + `audio/` + `settings.json`).

| Fichier | Rôle |
|---|---|
| `app/main.py` | routes : login mot de passe, `/oauth/login` Gemini, fils, tour de chat en NDJSON, upload audio, `/api/tts`, `/api/anki`, `/api/progress` |
| `app/coach.py` | cœur : assemblage du prompt système (3 `.md` + état live), 4 outils (`save_progress`, `request_recording`, `hear_recording`, `set_channels`), boucle de streaming, enregistrement des prises, marqueur `[tâche: …]` |
| `app/gemini.py` | Gemini via **OAuth Antigravity** (PKCE, redirect épinglé `localhost:51121`, projet `loadCodeAssist`, SSE `streamGenerateContent`), jamais de clé API |
| `app/opencode.py` | provider alternatif OpenCode Go (`OPENCODE_API_KEY`) |
| `app/notebook.py` | domaine « carnet » : validation stricte, application des patchs, révisions SRS locale (intervalles 1/3/7/14/30), `status()`, `report_data()` |
| `app/db.py` | SQLite : threads, messages (parts bruts Gemini rejoués), versions du carnet (append-only), chrono, demandes d'enregistrement |
| `app/timer.py` | chrono serveur, périodes `coach`/`learner`/`pause`, `time_confirmation` > 20 min |
| `app/anki.py` | export `.apkg` via genanki (modèle et IDs figés), cartes par jour + cumulatif |
| `app/tts.py` | Cartesia Sonic, cache disque par (texte, voix, vitesse), `language: "ko"` en dur |
| `app/static/` | UI chat : micro, audio cliquable (`#say`), prefill de réponses, drawer, `/progres`, thème, PWA |
| `coach/*.md` | **les prompts** : `coach.md` (protocole), `programme.md` (13 semaines), `sources.md` |
| `deploy/` | compose + Caddy branchés sur le réseau `movie-together`, wizard SSH, backup nocturne |
| `tests/` | 10 modules `unittest` + 1 test node (`prefill.test.mjs`) |

Déjà générique / réutilisable tel quel : le moteur de fils et de messages, la
boucle d'outils, le chrono, l'upload et l'écoute réelle des vocaux
(`inlineData`), le carnet versionné, l'export Anki, le cache TTS.

## 2. Ce qui est spécifique et à retirer

**Traces personnelles** (nom de l'apprenant dans 17 fichiers, nom de son
entourage dans 1) :

- `coach/coach.md` : identité du coach, une personne de l'entourage, le paquet
  `dm-*` de cartes issu d'échanges privés, l'échéance 8 sept. → 8 déc. 2026, le syndrome
  LoL/Minecraft, l'historique J1/J2, le rappel à l'ordre après absence.
- `coach/programme.md` : « Campagne coréen · 8 septembre → 8 décembre 2026 »,
  le calendrier 13 semaines, le bilan final du 8 décembre, le réglage « après
  J2 », le diagnostic J1, l'IME coréen.
- `coach/sources.md` : sources coréennes (Nuri Sejong, NIKL, 태웅쌤, AnkiDroid).
- `app/coach.py` : `SIDE_SYSTEM` (« séance de coréen de Florian »), `KICKOFF`,
  `FINISH`, libellés d'outils, `coreen-{date}.apkg`.
- `app/anki.py` : `Coreen-Florian`, deck `Coreen::Florian`, tags `coreen_florian`.
- `app/tts.py` : `language: "ko"`, voix par défaut coréenne, regex hangeul.
- `app/static/*` : titres « Coach coréen », manifeste, regex `coreen-*.apkg`.
- `app/notebook.py` : `target` (échéance) **obligatoire** et postérieure à
  `start` ; `status()` en déduit semaine et jours restants ; `daily_recap()`
  itère de `start` à `target`.

**Ajouté en dur dans le carnet** : le barème 0–4 par compétence, les LP et le
rang interne (Placement→Platine), les 13 semaines, la cible « conversation
avec une amie banmal/poli », les catégories de prises (`presentation`,
`journee`, `film`, `lecture`, `conversation`) et les modes (`spontane`,
`lecture`, `entraine`).

## 3. Architecture cible

1. **Onboarding au premier lancement** (remplace l'import korean-learn) :
   la langue cible, la variante/registre visé, l'objectif en texte libre
   (« parler avec une amie », « lire des mangas », …), le niveau déjà connu,
   la cadence souhaitée, l'accès audio (écoute / parole). Ces réponses
   créent le carnet (`profile`) et un premier `prep`.
   → le coach en déduit les situations, le vocabulaire et les exercices.
2. **Prompts templatés** : `coach/*.md` deviennent des gabarits avec des
   variables (`{{langue}}`, `{{objectif}}`, `{{niveau}}`, `{{registre}}`…),
   rendus à l'assemblage (`system_prompt`). Plus rien de nominatif.
3. **Niveau** : déclaré à l'onboarding puis vérifié par un premier diagnostic
   court ; les paliers 0–4 restent la mesure interne, affichés comme
   « niveau estimé » sans promettre une équivalence CECRL.
4. **Plus d'échéance** : `target` devient optionnel (objectif daté seulement
   si l'apprenant en donne un) ; les règles du carnet, `status()` et la page
   progression s'adaptent.
5. **Coach auto-critique** : à chaque clôture, feedback apprenant
   (trop facile / bien / trop dur) + auto-critique écrite du coach, stockés
   dans le carnet ; la séance suivante reçoit l'historique de calibrage et des
   règles d'ajustement explicites (monter la nouveauté/difficulté, décomposer,
   une seule variable à la fois, plafond par séance) et journalise l'effet.
6. **Langue paramétrable** : table langue → voix Cartesia + code langue,
   détection d'écriture par langue pour les textes « audibles », consigne IME
   générique ; l'écoute s'appuie sur l'audio TTS généré (les extraits
   institutionnels vérifiés à la main ne sont pas transposables).
7. **Contexte multi-langues** : plus de `.agents/` (skills d'agent de
   l'auteur), plus de `poc/` (scripts de recherche), plus d'import
   korean-learn, déploiement générique (run local + Dockerfile/compose
   autonome, pas de dépendance au Caddy de movie-together).

## 4. Étapes

1. **Reconnaissance** (fait) : ce document.
2. Décisions des questions ouvertes ci-dessous.
3. Squelette `language-coach` : portage du moteur (db, timer, notebook, gemini,
   tts, anki, static), renommage, repo GitHub privé, tests migrateurs verts.
4. Onboarding + carnet sans échéance + page réglages.
5. Prompts templatés génériques (suppression de toute trace personnelle).
6. Boucle d'auto-critique et de calibrage + tests.
7. Déploiement générique + documentation de prise en main.

## 5. Questions ouvertes

1. Mono-utilisateur auto-hébergé (chacun son instance, ses clés, son compte
   Google) ou instance partagée multi-comptes ? — le login Gemini est un
   OAuth Antigravity lié à un compte et épinglé sur `localhost:51121`, donc le
   multi-utilisateur propre est un chantier bien plus lourd.
2. Langues : n'importe laquelle (voix choisie dans Cartesia) ou liste curatée ?
3. Niveau : déclaratif, diagnostic joué, ou déclaratif + vérifié ?
4. Rythme : aucun calendrier, ou objectif/cadence optionnels ?
5. Auto-critique : jusqu'aux paramètres de séance, ou le coach réécrit-il
   aussi ses propres instructions ?
6. Périmètre : ce que je retire (`.agents/`, `poc/`, import, deploy
   movie-together, `docs/research`, sources coréennes), l'écoute par TTS
   Cartesia au lieu d'extraits vérifiés à la main, le barème/LP conservé,
   dépôt privé `xelema/language-coach`.
