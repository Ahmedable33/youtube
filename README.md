# Automatisation de publication YouTube (Python)

Ce projet fournit une CLI en Python pour uploader et programmer la publication de vidéos sur YouTube via l'API YouTube Data v3.

## 1) Prérequis

- Python 3.9+ (recommandé)
- Un projet dans Google Cloud Console avec l'API YouTube Data v3 activée
- Identifiants OAuth 2.0 de type "Application Desktop" (fichier `client_secret.json`)
- ffmpeg installé sur votre système (requis par `yt-dlp` et la commande `enhance` pour l'encodage/merge)
- (Optionnel) Variable d'environnement `OPENAI_API_KEY` si vous utilisez la génération IA (`ai-meta`)

## 2) Installation

```bash
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
```

## 3) Configuration OAuth

- Placez votre fichier `client_secret.json` dans `config/client_secret.json` (dossier ignoré par git).
- Fallback automatique: si non trouvé dans `config/`, le script tentera `./client_secret.json` à la racine du projet.
- Le premier lancement ouvrira votre navigateur pour autoriser l'application.
- Le token sera stocké dans `config/token.json`.

## 4) Exemple de configuration YAML

Fichier: `config/video.example.yaml`

```yaml
# Chemins de fichiers
video_path: ./video.mp4
thumbnail_path: ./thumbnail.jpg  # optionnel

# Métadonnées
title: "Mon titre automatisé"
description: |
  Ma description détaillée sur plusieurs lignes.
tags: ["automation", "python"]
category_id: 22  # 22 = People & Blogs (par défaut)

# Statut et planification
privacy_status: private  # private | public | unlisted
publish_at: "2025-08-31T12:00:00Z"  # Optionnel (RFC3339/UTC). Requiert privacy_status=private.

# Enfants (optionnel)
made_for_kids: false

# Amélioration qualité (optionnel)
enhance:
  enabled: true            # si true, améliore automatiquement avant upload
  quality: youtube         # low | medium | high | youtube | max (sert de préréglage par défaut)
  codec: h264              # h264 | hevc | vp9 | av1
  hwaccel: auto            # none | auto | videotoolbox (auto => videotoolbox sur macOS)
  scale: 1080p            # 720p|1080p|1440p|2160p|WIDTHxHEIGHT|1.5x|2x
  fps: 30                 # optionnel
  denoise: true           # hqdn3d
  sharpen: true           # unsharp
  deinterlace: false      # yadif
  color_fix: true         # léger contraste/saturation
  crf: 18                 # ignoré si bitrate défini (par défaut selon preset, sinon 18)
  bitrate: null           # ex: "6M". Si défini, ignore CRF
  preset: slow            # ultrafast…veryslow (par défaut selon preset, sinon medium)
  reencode_audio: true
  audio_bitrate: "192k"
```

## 5) Utilisation (CLI)

### Upload

Avec un fichier de config:

```bash
python main.py upload --config config/video.example.yaml
```

Pré-amélioration (ffmpeg) avant upload : activez `enhance.enabled: true` dans la config (voir ci-dessus),
ou utilisez le flag `--pre-enhance` et des overrides en ligne de commande :

```bash
python main.py upload --config config/video.example.yaml --pre-enhance \
  --enhance-scale 1080p \
  --enhance-denoise --enhance-sharpen --enhance-color-fix \
  --enhance-crf 18 --enhance-preset slow \
  --enhance-reencode-audio
```

Overrides disponibles (équivalent aux options de `enhance`) :

- `--enhance-quality` low | medium | high | youtube | max
- `--enhance-codec` h264 | hevc | vp9 | av1
- `--enhance-hwaccel` none | auto | videotoolbox
- `--enhance-scale` 720p | 1080p | 1440p | 2160p | WIDTHxHEIGHT | 1.5x | 2x
- `--enhance-fps` Nombre (ex : 30)
- `--enhance-denoise`
- `--enhance-sharpen`
- `--enhance-deinterlace`
- `--enhance-color-fix`
- `--enhance-crf` Entier 0-51 (par défaut: selon preset, sinon 18)
- `--enhance-bitrate` (ex : 6M) — si défini, ignore CRF
- `--enhance-preset` ultrafast…veryslow (par défaut: selon preset, sinon medium)
- `--enhance-reencode-audio`
- `--enhance-audio-bitrate` (par défaut 192k)
- `--enhance-output` pour le fichier de sortie (par défaut `<video>.enhanced.mp4`)

Sans fichier de config (arguments explicites):

```bash
python main.py upload \
  --video ./video.mp4 \
  --title "Titre" \
  --description "Description" \
  --tags automation python \
  --category-id 22 \
  --privacy private \
  --publish-at "2025-08-31T12:00:00Z" \
  --thumbnail ./thumbnail.jpg
```

Chemins OAuth personnalisés (optionnels):

```bash
python main.py upload --config config/video.example.yaml \
  --client-secrets config/client_secret.json \
  --token-file config/token.json
```

Notes:

- Pour une planification, YouTube requiert généralement `privacy_status=private` au moment de l'upload avec `publish_at` au format RFC3339 UTC (suffixe `Z`).
- L'upload est repris automatiquement (resumable upload) et inclut un backoff exponentiel pour les erreurs temporaires.

### Génération IA de métadonnées (`ai-meta`)

Nécessite d'avoir `OPENAI_API_KEY` dans votre environnement. Exemple :

```bash
export OPENAI_API_KEY=sk-xxxx
python main.py ai-meta \
  --topic "Automatiser YouTube avec Python" \
  --target-keywords python automation api \
  --language fr \
  --tone informatif \
  --model gpt-4o-mini \
  --out-config config/video.yaml \
  --video-path ./video.mp4 \
  --print
```

Cette commande affiche un aperçu (titre, description, tags) et peut écrire directement ces champs dans un YAML (`--out-config`).

### Ingestion vidéo (`ingest`)

Télécharger une vidéo avec `yt-dlp` et convertir en mp4 (si possible) :

```bash
python main.py ingest "https://www.youtube.com/watch?v=XXXXXXXXX" \
  --output-dir downloads \
  --ext mp4
```

La commande renvoie le chemin complet du fichier téléchargé.

### Amélioration de qualité (`enhance`)

Améliorer la qualité d'une vidéo (upscale, débruitage, netteté, désentrelacement, correction légère) via ffmpeg :

```bash
python main.py enhance \
  --input ./input.mp4 \
  --output outputs/enhanced.mp4 \
  --quality youtube \
  --codec h264 \
  --hwaccel auto \
  --denoise --sharpen --color-fix \
  --reencode-audio
```

Options utiles :

- `--scale`: 720p | 1080p | 1440p | 2160p | WIDTHxHEIGHT | 1.5x | 2x
- `--fps`: forcer la cadence (ex: 30)
- `--denoise`: réduction de bruit (hqdn3d)
- `--sharpen`: renforcer la netteté (unsharp)
- `--deinterlace`: désentrelacer (yadif)
- `--color-fix`: léger ajustement contraste/saturation
- `--quality`: préréglage global (low | medium | high | youtube | max)
- `--codec`: h264 | hevc | vp9 | av1
- `--hwaccel`: none | auto | videotoolbox (auto => videotoolbox sur macOS)
- `--crf`: qualité H.264 (0-51, plus bas = meilleure qualité, par défaut selon preset, sinon 18)
- `--bitrate`: fixe un débit vidéo (ex: 6M) au lieu d'un CRF
- `--preset`: préréglage x264 (ultrafast…veryslow; par défaut selon preset, sinon medium)
- `--reencode-audio` et `--audio-bitrate`: réencoder l'audio en AAC

Remarques codecs :

- `hevc` (H.265) nécessite `libx265` compilé avec ffmpeg. Ajout de `-tag:v hvc1` pour meilleure compatibilité mp4.
- `vp9` utilise `libvpx-vp9` avec `-row-mt 1` et map de `--preset` vers `-cpu-used`.
- `av1` utilise `libaom-av1` avec map de `--preset` vers `-cpu-used` (valeurs 0-8). Encodage beaucoup plus lent selon la qualité.

Accélération matérielle :

- `videotoolbox` utilise les encodeurs matériels Apple (`h264_videotoolbox`, `hevc_videotoolbox`).
- En mode matériel, la qualité est réglée via `-q:v` (0-63). Nous effectuons un mapping approximatif depuis `--crf`.
- L’option `auto` sélectionne automatiquement `videotoolbox` sur macOS, sinon désactive l’accélération.

Préréglages de qualité :

- `low` : CRF 23, preset fast, denoise
- `medium` : 1080p, CRF 20, preset medium, denoise, sharpen, color-fix
- `high` : 1440p, CRF 18, preset slow, denoise, sharpen, color-fix
- `youtube` : 1080p, CRF 20, preset slow, denoise, sharpen, color-fix
- `max` : 2160p, CRF 17, preset slow, denoise, sharpen, color-fix

## 6) Planification (cron)

Exemple: exécuter tous les jours à 09:00.

```cron
0 9 * * * /usr/bin/python3 /chemin/vers/youtube-automation/main.py upload --config /chemin/vers/video.yaml
```

## 7) Sécurité

- Ne commitez jamais `config/client_secret.json` ni `config/token.json`.
- Les deux fichiers sont ignorés par `.gitignore`.

## 8) Dépannage

- Authentification: supprimez `config/token.json` et relancez pour refaire le flux OAuth si nécessaire.
- Échecs d'upload: vérifiez le format/poids de la vidéo et vos quotas d'API.
- `OPENAI_API_KEY` manquant: la commande `ai-meta` lèvera une erreur si la variable n'est pas définie.
- ffmpeg manquant: `yt-dlp` et la commande `enhance` nécessitent ffmpeg pour convertir/merger. Installez-le via votre gestionnaire de paquets (macOS: `brew install ffmpeg`).

## 9) Licence

Ce projet est fourni tel quel, sans garantie. Utilisez-le conformément aux Conditions d'utilisation de YouTube et de Google Cloud.
