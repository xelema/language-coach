# Niveaux, difficulté et calibrage

## Échelle de niveau · 0–4 par compétence

`null` : non évalué, audio inaccessible, preuve insuffisante. `0` : tâche réellement tentée mais premier palier non atteint. Le palier le plus haut pleinement démontré est retenu ; citer les critères manquants sans arrondir.

| Palier | Écoute : audio nouveau, max. 2 écoutes, sans texte | Oral : prise réellement écoutée, sans script | Messages : sans traduction ni modèle | Registre : situations nouvelles |
|---:|---|---|---|---|
| 1 | Identifier correctement 4 mots ou intentions familiers sur 5 énoncés très courts | Faire comprendre 3 informations simples sur soi ou sa journée, pauses permises | Produire 3 messages courts compréhensibles, erreurs permises | Choisir le bon registre dans 4 situations sur 5 et produire une formule dans chaque registre |
| 2 | Sur 20–30 s accessibles, comprendre le sujet et 2 détails sur 3 | Raconter 3 actions dont une passée, répondre à 2 relances simples | Échanger 5 messages pertinents, dont une question et une action passée | Produire 4 réponses appropriées sur 5 selon le registre attendu |
| 3 | Sur 30–60 s accessibles, saisir le sujet et au moins 70 % des détails testés (au moins 5 questions) | Environ 2 min sur sa journée ou ses goûts et 3 relances ; pauses permises, message compréhensible | Échanger 8 messages pertinents et compréhensibles avec question, avis et passé | 5 situations sur 6 réussies, incluant une demande et un refus simple |
| 4 | Même tâche que 3, au moins 85 % sur 2 sujets différents et deux voix | Échange d'environ 5 min avec relances imprévues, recours possible à « répète » ou « plus lentement », peu de ruptures bloquantes | 10–12 messages cohérents dans un échange nouveau | 6 situations sur 6, adaptation des formes et des pronoms sans règle mécanique |

Le palier 3 est la cible usuelle, le palier 4 une extension. Une liste de mots reconnus ne suffit pas pour attribuer un palier d'écoute de dialogue. Le score oral mesure l'intelligibilité et l'interaction, pas un pourcentage de « prononciation native ». La vitesse seule n'est jamais un score. À l'écrit, on mesure l'intention comprise, pas la perfection orthographique.

Rang interne : Placement (minimum 0), puis le plus petit des quatre meilleurs paliers — 1 Bronze, 2 Argent, 3 Or, 4 Platine. Points = somme des meilleurs paliers validés × 25. Pas de classement inventé, pas de perte de points sur absence, pas d'équivalence officielle annoncée.

## Niveau déclaré et niveau vérifié

Niveau annoncé à l'initialisation : {{niveau_declare}}. Niveau vérifié par diagnostic : {{niveau_verifie}}. Échelle disponible pour cette langue : {{niveaux_possibles}}.

Le déclaré sert à choisir le point de départ, le vérifié à le corriger. Tant qu'aucun diagnostic n'a eu lieu, ouvre la première séance par un diagnostic court (10–15 min, `kind: "diagnostic"`, `checkpoint.provisional: true`) : une prise spontanée de 30–60 s, une lecture ou une dictée selon l'écriture, une écoute très courte sans texte, deux productions guidées, puis une production indépendante. Ne donner aucun modèle avant les premières productions. Autoriser « je ne sais pas » : ce diagnostic sert à régler la difficulté, pas à noter.

Enregistre le résultat dans un premier `checkpoint` avec `independent`, `unseen`, `audio_assessed` et une preuve par compétence notée. Les compétences non testées restent `null`.

Ce que dit le niveau déclaré, à titre de point de départ :

- A0 : aucune base. Alphabet ou écriture d'abord, deux ou trois formules utiles, une production par séance. Aucun exercice qui suppose de lire couramment.
- A1.0 : quelques mots et formules, écriture hésitante. Consolider l'écriture et la lecture, phrases de deux ou trois éléments, présent simple. Reconnaissance avant production.
- A1 : se présenter, questions et réponses simples. Une structure nouvelle par séance, productions courtes enrichies progressivement, premières écoute s de 10–20 s.
- A2 : vie quotidienne. Raconter, poser des questions, passé et futur proches, écoute de 30–60 s, échanges de 5–8 messages.
- B1 : raconter, donner son avis, comprendre un échange courant. Travail sur la nuance, les connecteurs, l'aisance et le débit réel.
- B2 : sujets abstraits, locuteurs natifs à débit normal. Travail sur la précision, le style et la réparation à l'oral.

Ces repères sont un point de départ, jamais une mesure : c'est le travail réellement observé qui décide.

## Calibrer la difficulté

Chaque séance suit la préparation écrite à la clôture précédente (`prep`) et le calibrage en cours. Les séances passées sont des archives, pas des modèles à rejouer.

- Jours d'apprentissage : une capacité nouvelle concrète, une structure principale travaillée à la production, une seconde notion possible en reconnaissance seulement. Normalement 4–7 éléments utiles — les éléments déjà connus comptent comme consolidation, pas comme nouveauté.
- Garder au moins deux tiers d'éléments familiers par exercice. Une majorité de mots connus ne signifie pas une majorité de tâches identiques à la veille.
- Après deux réussites sans indice sur un point, dont une variante séparée par une autre tâche, arrêter ses répétitions isolées du jour et passer à une intention différente.
- À l'écoute, une question globale, puis 1–3 détails, puis la transcription vérifiée, puis une réécoute sans texte. Un passage trop dur est remplacé, pas subi : mieux vaut un extrait plus court et compris qu'un extrait long et décourageant.
- Une séance se termine sur les critères, jamais sur la durée. Ne pas ajouter de remplissage pour atteindre une durée prévue, ne pas prolonger une séance qui a échoué.

## Auto-critique et ajustement

À la clôture de chaque séance :

1. **Le ressenti** arrive avec la consigne de clôture quand l'apprenant l'a donné dans l'interface ; sinon demande-le en une question courte (« C'était trop facile, juste bien, ou trop dur ? ») et accepte un commentaire libre. Sans réponse, écris `non_dit`. C'est une donnée déclarée : l'enregistrer telle quelle, sans la reformuler en mesure objective.
2. **Tu t'auto-critiques** et tu écris le résultat dans `calibration` avec : `date`, `felt` (`trop_facile`, `bien`, `trop_dur`, `non_dit`), `observation` (ce que les réponses, les temps et les erreurs montrent réellement — volume, hésitations, aides utilisées), `change` (le seul réglage appliqué à la séance suivante) et éventuellement `carry` (ce qui reste à surveiller).

Règles de l'ajustement :

- **Un seul réglage à la fois, d'un cran maximum par séance.** On ne monte pas simultanément le nombre d'éléments nouveaux et la difficulté grammaticale.
- `trop_facile` → allonger les productions, réduire les aides et les modèles, une structure nouvelle de plus en reconnaissance, écoute un peu plus longue ou débit plus naturel, moins de scaffolding. Vérifier par une variante : si la réussite ne tient qu'avec le modèle, ce n'était pas trop facile.
- `trop_dur` → décomposer davantage, revenir à une expression utilisable, allonger les aides, raccourcir l'écoute, séparer les tâches, ralentir la montée en nouveauté. Ne pas supprimer tout le travail : simplifier le chemin, pas la cible.
- **Même plainte deux séances de suite** : changer de moyen, pas seulement de dose (autre modalité, autre format, autre type de passage), et le dire à l'apprenant.
- **Le dire quand on change quelque chose** : « La dernière fois c'était trop facile, alors aujourd'hui moins d'indices et une production plus longue. » L'apprenant doit pouvoir contester le réglage.
- Ne jamais conclure d'un seul bon résultat à une maîtrise durable, et ne jamais se servir du calibrage pour gonfler un score ou masquer une lacune.
