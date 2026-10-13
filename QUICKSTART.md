# QUICKSTART — mettre le coach en route

Vous clonez le projet et vous voulez une séance dans les dix minutes. Voilà
l'ordre exact, ce qui bloque si une pièce manque, et où sont les fichiers.

## 1. Prérequis

- **Python 3.11 ou plus** (`python3 --version`). Rien d'autre n'est à installer :
  `./run.sh` crée l'environnement virtuel et les dépendances.
- Un **compte Google** ayant accès à Gemini (le même accès que l'application
  Antigravity) : c'est le chemin du modèle, il n'y a aucune clé API à acheter.
- Une **clé Cartesia** (Sonic) pour entendre la langue cible. Sans elle,
  l'application fonctionne mais le texte n'est pas audible.
- *(facultatif)* Une clé **OpenCode Go** pour utiliser d'autres modèles.

## 2. Installer et lancer

```bash
git clone https://github.com/xelema/language-coach.git
cd language-coach
./run.sh
```

Le premier lancement crée l'environnement, **crée le fichier `.env` à partir de
`.env.example`** et demande ce qui manque (mot de passe du site, clé Cartesia) —
voir la section suivante. Il affiche ensuite `http://localhost:51121`.
**Le port 51121 n'est pas un détail** : la redirection OAuth de Google est
enregistrée dessus pour l'application Antigravity. Si ce port est occupé chez
vous, vous pouvez changer de port (`LC_PORT=...`) mais la connexion Google
échouera tant que c'est un autre port.

### Sur Windows (Git Bash)

`./run.sh` fonctionne tel quel : il détecte `.venv/Scripts/python.exe`. Si le
script perd ses droits d'exécution, `bash run.sh` marche aussi.

## 3. Ce que le premier lancement demande

Le fichier `.env` n'est pas à écrire à la main : `./run.sh` le crée (copie de
`.env.example`) et **demande seulement ce qui manque**. La saisie est masquée, et
les valeurs passent par le clavier, pas par la ligne de commande — elles ne
finissent donc pas dans l'historique du shell.

- `./run.sh setup` : repose les questions à tout moment.
- Sans terminal interactif (service détaché, conteneur), rien n'est demandé : un
  court état part dans le journal et l'application démarre.
- Le fichier est ensuite lu automatiquement au démarrage ; une variable déjà
  exportée dans le shell garde la priorité sur lui.

1. **Mot de passe du site** (obligatoire) — saisi masqué au clavier, seul son
   hash est écrit dans le fichier. Sans lui, la page de connexion refuse tout le
   monde, et le dit explicitement. Équivalent manuel : `./run.sh hash`.
2. **Clé Cartesia** (facultatif) — c'est elle qui rend la langue cible audible.
   Elle se crée sur **https://play.cartesia.ai/keys** : se connecter au tableau de
   bord Cartesia, section **API Keys**, créer une clé standard (de la forme
   `sk_car_…`). Elle est vérifiée auprès de l'API au moment de la saisie ; si elle
   ne répond pas, elle est conservée avec un avertissement plutôt que refusée.
   Sans clé : tout fonctionne, sauf le son.
3. **Modèle** — rien à faire par défaut : ouvrez `http://localhost:51121`,
   connectez-vous, puis cliquez sur le lien **Connexion Google** (`/oauth/login`).
   Le jeton reste dans `data/`, il ne part jamais dans le navigateur.

Alternative si vous préférez une clé d'API au lieu d'OAuth :
`LC_PROVIDER=opencode` et `OPENCODE_API_KEY=oc_...`.

## 4. La mise en route (une seule fois)

Au premier accès, l'application ouvre `/onboarding` et demande :

- la **langue** à apprendre (japonais, coréen) ;
- **pourquoi** vous l'apprenez — c'est la réponse la plus importante : le coach
  en tire les situations et le vocabulaire de chaque exercice ;
- votre **niveau déjà connu**, parmi les paliers proposés pour cette langue. La
  première séance commence par un diagnostic court qui le vérifie et le corrige ;
- votre **nom** (facultatif), la **cadence** souhaitée, un **objectif daté**
  (facultatif : aucune échéance n'est imposée par défaut) ;
- *(facultatif)* des **vidéos** : le bouton « Chercher des vidéos » lance une
  vraie recherche dans la langue choisie, vous cochez celles qui vous semblent
  adaptées, et seules celles-là entrent dans le carnet.

Le dernier écran propose la **connexion Google** si elle n'a pas encore été faite :
sans elle, le coach ne peut pas répondre. La même connexion reste accessible
depuis les Paramètres, et un bandeau la rappelle dans le fil tant qu'elle manque.

L'écoute et la parole ne sont pas demandées ici : elles se déclarent à
l'ouverture de **chaque** séance (case « je peux écouter », « je peux parler »),
parce qu'elles changent d'un jour à l'autre — un trajet en train n'autorise pas
les mêmes exercices qu'une séance au calme.

Tout est modifiable ensuite dans **Paramètres** (nom, niveau, objectif, cadence,
échéance, voix, fuseau horaire, fournisseur et modèle).

## 5. Une séance, puis un rythme

- **Commencer une séance** : le coach annonce la mission et le premier défi,
  puis un exercice à la fois. Vous pouvez écrire, envoyer un vocal (bouton 🎙),
  cliquer sur n'importe quel texte de la langue cible pour l'entendre (vitesse
  normale ou lente), poser une question dans le fil « ? » sans interrompre la
  séance. Le chronomètre tourne côté serveur ; ⏸ met en pause.
- **Terminer** : le bouton ■ demande d'abord comment c'était (*trop facile*,
  *juste bien*, *trop dur*, ou rien). Le coach écrit ce ressenti tel quel dans sa
  calibration, avec ce qu'il a observé et **le seul réglage** qu'il appliquera à
  la séance suivante. Le fil affiche ce calibrage : vous pouvez le contester.
- **Progression** : menu ☰ → *Progression* — profil, rangs, minutes, calendrier
  des jours travaillés, calibrage des séances, vidéos validées, prises audio.
- **Cartes** : menu ☰ → *Téléchargements* pour les paquets Anki (`.apkg`), à
  ouvrir dans AnkiDroid. Anki reste le seul ordonnanceur quand il est activé.

## 6. Ce qui marche sans quoi

| Il manque | Conséquence |
|---|---|
| `LC_PASSWORD_HASH` | personne ne peut se connecter : à générer avant tout |
| Connexion Google (ou clé OpenCode) | pas de coach : l'interface répond mais aucune séance ne démarre |
| `CARTESIA_API_KEY` | tout fonctionne, sauf le son : le texte de la langue cible n'est pas cliquable-pour-entendre |
| `yt-dlp` absent ou YouTube qui bloque | seul le bouton « Chercher des vidéos » échoue, avec son message ; la mise en route continue |
| Micro | les exercices oraux deviennent de l'écrit et les prises sont reportées, sans pénalité |

## 7. Où sont les données, comment sauvegarder

Tout vit dans `data/` (ignoré par git) : `coach.db` (fils, messages, carnet
versionné), `audio/` (vocaux, prises, extraits de synthèse en cache),
`settings.json` (fournisseur, modèle, voix, fuseau), `antigravity_token.json`
(jeton OAuth — **à ne jamais partager**).

À côté, le fichier `.env` porte les secrets (hash du mot de passe, clé Cartesia)
et n'est créé qu'avec les droits du propriétaire. Il est ignoré par git : ne le
mettez jamais dans un dépôt ni dans une sauvegarde partagée.

Sauvegarder = copier `data/`. Supprimer le projet = supprimer le dossier (le
`data/` avec lui). Mise à jour = `git pull` puis `./run.sh` (les dépendances se
réinstallent si elles ont changé).

## 8. Ajouter une langue, dépanner

- **Ajouter une langue** : créez `app/languages/<code>.py` avec une variable
  `LANGUAGE` (copiez `app/languages/japanese.py`). Écriture cible, voix Cartesia,
  registres, aide à la saisie, ressources, notes pédagogiques : tout est là.
  Aucun autre fichier à modifier, le paquet est découvert au démarrage.
- **Mot de passe refusé (401)** alors qu'il est écrit dans `.env` : la ligne est
  probablement encore commentée (`# LC_PASSWORD_HASH=...`) ou le serveur n'a pas
  été relancé depuis la modification. Si le message affiché est « Aucun mot de
  passe configuré », c'est que l'application ne trouve pas `LC_PASSWORD_HASH` :
  vérifier le nom du fichier (`.env`, pas `.env.txt`) et son emplacement (à côté
  de `run.sh`).
- **`./run.sh hash` n'existe pas** : le dépôt est antérieur à l'ajout de cette
  commande (`git pull`) — sinon, utiliser l'interpréteur du venv, qui n'est pas
  au même endroit sous Windows (`.venv/Scripts/python.exe`, pas `.venv/bin/`).
- **Le port 51121 est pris** : `ss -ltnp | grep 51121` (Linux) ou
  `netstat -ano | findstr 51121` (Windows), puis libérez-le — la connexion
  Google a besoin de ce port.
- **« no model access »** : le jeton OAuth a expiré ou n'a jamais été posé →
  rouvrir `/oauth/login`.
- **La voix ne marche pas** : vérifier `CARTESIA_API_KEY`, puis le choix de voix
  dans Paramètres (la liste est vide si Cartesia n'est pas configuré).
- **Une vidéo proposée ne convient pas** : ne la cochez pas. Le coach ne
  s'appuie que sur ce que vous avez gardé, et ne devine jamais ce qui s'y dit.
