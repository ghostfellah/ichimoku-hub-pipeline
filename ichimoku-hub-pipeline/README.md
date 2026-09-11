# Ichimoku Hub Pipeline

Automatise, via GitHub Actions, la partie du pipeline Ichimoku Hub qui a
besoin d'un accès réseau à YouTube (détection des nouvelles vidéos +
téléchargement/nettoyage des sous-titres). L'extraction des concepts et la
rédaction dans Notion restent faites par la tâche planifiée Claude, qui lit
ensuite les transcriptions produites ici.

```
sources.yml                        <- liste des chaînes YouTube suivies
scripts/detect_new_videos.py       <- Étape 1 : nouvelles vidéos -> Notion
scripts/extract_transcripts.py     <- Étape 2 (partie mécanique) : sous-titres -> transcripts/*.txt
scripts/notion_client.py           <- petit client API Notion partagé
transcripts/                       <- transcriptions nettoyées, committées par le workflow
.github/workflows/pipeline.yml     <- le cron GitHub Actions
```

## Installation

### 1. Intégration Notion

1. Va sur https://www.notion.so/my-integrations → **New integration**.
2. Donne-lui un nom (ex. "Ichimoku Hub Pipeline"), associe-la à ton
   workspace, capacités : **Read content**, **Insert content**, **Update
   content**.
3. Copie le token (`ntn_...`).
4. Dans Notion, ouvre la base **📹 Vidéos — Sources (@KeiForex)** → menu
   `•••` → **Connexions** → ajoute l'intégration créée. (Optionnel : fais
   pareil sur **📚 Concepts Ichimoku** si tu veux que ce même token serve
   plus tard à d'autres automatisations.)

### 2. Secret GitHub

Dans ce repo : **Settings → Secrets and variables → Actions → New
repository secret**

- Nom : `NOTION_TOKEN`
- Valeur : le token copié à l'étape précédente

### 3. Permissions du workflow

**Settings → Actions → General → Workflow permissions** → sélectionne
**Read and write permissions** (nécessaire pour que le workflow puisse
committer les transcriptions dans `transcripts/`).

### 4. Activer le workflow

Le repo étant privé, va dans l'onglet **Actions** et active les workflows
si demandé. Le pipeline tourne ensuite automatiquement tous les jours à
9h00 UTC, et est déclenchable manuellement via **Actions → Ichimoku Hub
Pipeline → Run workflow**.

## YouTube bloque les runners GitHub Actions (important)

Les IPs partagées des runners GitHub-hosted sont très souvent bloquées ou
rate-limitées par YouTube (`429`, "Sign in to confirm you're not a bot")
dès qu'on dépasse le simple listing "flat playlist" — c'est-à-dire pour
**toute récupération de métadonnées vidéo détaillées (dates) et tout
téléchargement de sous-titres**. Symptôme typique : le workflow se termine
en vert, mais `SUMMARY:` indique 0 vidéo ajoutée / 0 transcription, avec des
lignes `rate-limited` ou `pas de date` dans les logs.

**Solution : passer des cookies YouTube à yt-dlp.** Une requête authentifiée
avec les cookies d'une session connectée est beaucoup moins souvent bloquée.

1. Connecte-toi à YouTube dans ton navigateur avec un compte Google
   (un compte secondaire/dédié est plus prudent qu'un compte principal,
   puisque ces cookies donnent l'équivalent d'un accès à la session).
2. Installe une extension du type **"Get cookies.txt LOCALLY"** (Chrome/
   Firefox), va sur youtube.com, exporte les cookies au format Netscape
   (`cookies.txt`).
3. Encode le fichier en base64 :
   ```
   base64 -w0 cookies.txt > cookies.b64.txt   # Linux
   base64 -i cookies.txt -o cookies.b64.txt   # macOS
   ```
4. Ajoute un secret GitHub `YOUTUBE_COOKIES_B64` avec le contenu de
   `cookies.b64.txt`.
5. Le workflow le décode automatiquement à chaque run (étape "Decode
   YouTube cookies") et le passe à tous les appels yt-dlp via
   `--cookies`. Rien à faire côté scripts.

Ces cookies expirent / tournent avec le temps (généralement plusieurs
semaines à quelques mois) : si le pipeline recommence à ne rien produire
avec les mêmes symptômes (`rate-limited`, `pas de date`), regénère-les.

Sans ce secret configuré, le pipeline continue de fonctionner mais restera
probablement bloqué par YouTube comme observé aujourd'hui.

## Gérer les sources YouTube

Édite `sources.yml` :

```yaml
channels:
  - name: "@KeiForex"
    videos_url: "https://www.youtube.com/@KeiForex/videos"
    streams_url: "https://www.youtube.com/@KeiForex/streams"

  - name: "@UneAutreChaine"
    videos_url: "https://www.youtube.com/@UneAutreChaine/videos"
    streams_url: null
```

Commit + push : la prochaine exécution du workflow en tiendra compte,
aucune autre modification n'est nécessaire.

## Donner à Claude l'accès aux transcriptions (repo privé)

Le repo étant privé, la tâche planifiée Notion a besoin d'un token GitHub
en lecture seule pour aller chercher les fichiers dans `transcripts/` via
l'API GitHub (`api.github.com`, atteignable depuis l'environnement cloud de
Claude — contrairement à youtube.com).

1. Crée un **fine-grained personal access token**
   (https://github.com/settings/personal-access-tokens/new) :
   - **Repository access** : Only select repositories → `ichimoku-hub-pipeline`
   - **Permissions** : Contents → **Read-only** (rien d'autre)
   - Expiration : au choix (pense à le renouveler avant expiration, sinon
     Claude perdra l'accès aux transcriptions — pas aux vidéos déjà
     ajoutées, juste à la lecture des nouveaux fichiers).
2. Stocke ce token dans une page Notion privée (non partagée) dédiée à la
   config du pipeline — Claude ira la relire à chaque run. Ne le mets pas
   dans une page partagée ou publique.

## Statuts Notion utilisés par ce pipeline

| Statut              | Posé par            | Signifie                                                      |
|----------------------|----------------------|-----------------------------------------------------------------|
| ⏳ À traiter          | ce pipeline (nouvelle vidéo) | pas encore de transcription                              |
| 🔎 En cours           | ce pipeline (transcript prêt) | transcription disponible dans `transcripts/<id>.txt`, en attente de traitement par Claude |
| ✅ Traité / 🚫 Non pertinent | Claude (Notion) | concepts extraits (ou vidéo jugée non pertinente)         |

Si le téléchargement des sous-titres échoue après plusieurs essais (pas de
sous-titres disponibles, ou rate-limit persistant), la ligne est remise à
**⏳ À traiter** et sera retentée au prochain run.
