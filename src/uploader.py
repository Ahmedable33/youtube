from __future__ import annotations

import logging
import json
import random
import time
from pathlib import Path
from typing import Iterable, Optional
from datetime import datetime, timezone

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload


logger = logging.getLogger(__name__)


def _sanitize_language(lang: Optional[str]) -> Optional[str]:
    """Convertit les codes langue en BCP-47 simple acceptés par YouTube.

    - Mappe quelques codes 3 lettres fréquents vers 2 lettres (ISO 639-1)
    - Autorise les tags BCP-47 courants (ex: en, fr, en-US)
    - Si invalide/suspect: retourne None pour ne pas l'envoyer
    """
    if not lang:
        return None
    lang_str = lang.strip()
    if not lang_str:
        return None
    # Normaliser casse
    # On garde la casse des sous-tags régionaux (BCP-47 recommande en-GB, fr-FR)
    # mais on ne va pas imposer stricte normalisation ici.

    # Mapping commun 3->2
    map3 = {
        "eng": "en",
        "fra": "fr",
        "fre": "fr",
        "spa": "es",
        "deu": "de",
        "ger": "de",
        "por": "pt",
        "ita": "it",
        "ara": "ar",
        "jpn": "ja",
        "kor": "ko",
        "rus": "ru",
        "zho": "zh",
        "chi": "zh",
    }
    low = lang_str.lower()
    if low in map3:
        return map3[low]

    # Autoriser formes simples (2 lettres) et avec région (ex: en-US, fr-FR)
    if len(lang_str) == 2 and lang_str.isalpha():
        return lang_str.lower()
    if 2 <= len(lang_str) <= 8 and ("-" in lang_str or "_" in lang_str):
        # Remplacer underscore par tiret et retourner tel quel
        return lang_str.replace("_", "-")

    # Sinon on considère suspect
    logger.warning("Lang code suspect, ignoré: %s", lang_str)
    return None


def _to_rfc3339_utc(ts: str) -> Optional[str]:
    """Convertit une chaîne ISO en RFC3339 UTC '...Z' avec précision secondes.
    Retourne None si parsing échoue.
    """
    try:
        s = ts.strip()
        # Support 'Z' et offsets
        if s.endswith("Z"):
            s = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    except Exception as e:
        logger.warning("Timestamp non RFC3339, ignoré: %s (%s)", ts, e)
        return None


def _ensure_future_publish_at(
    publish_at: Optional[str], min_delta_minutes: int = 10
) -> Optional[str]:
    """Vérifie que publishAt est dans le futur, sinon le décale de min_delta_minutes.

    Retourne une chaîne RFC3339 UTC 'Z' ou None si input invalide.
    """
    if not publish_at:
        return None
    san = _to_rfc3339_utc(publish_at)
    if not san:
        return None
    try:
        dt = datetime.fromisoformat(san.replace("Z", "+00:00"))
        nowu = datetime.now(timezone.utc)
        if dt <= nowu:
            adj = nowu.replace(microsecond=0) + __import__("datetime").timedelta(
                minutes=min_delta_minutes
            )
            return adj.isoformat().replace("+00:00", "Z")
        return san
    except Exception:
        return san


def _build_service(credentials):
    return build("youtube", "v3", credentials=credentials)


def upload_video(
    credentials,
    *,
    video_path: str | Path,
    title: str,
    description: str = "",
    tags: Optional[Iterable[str]] = None,
    category_id: str | int = 22,
    privacy_status: str = "private",
    publish_at: Optional[str] = None,
    thumbnail_path: Optional[str | Path] = None,
    made_for_kids: Optional[bool] = None,
    embeddable: Optional[bool] = None,
    license: Optional[str] = None,  # "youtube" | "creativeCommon"
    public_stats_viewable: Optional[bool] = None,
    default_language: Optional[str] = None,  # ex: "fr"
    default_audio_language: Optional[str] = None,  # ex: "fr"
    recording_date: Optional[str] = None,  # RFC3339 (ex: 2025-09-05T12:00:00Z)
) -> dict:
    """
    Uploade une vidéo sur YouTube avec reprise (resumable) et planification optionnelle.

    Retourne la réponse API finale contenant notamment l'ID de la vidéo.
    """
    service = _build_service(credentials)
    p = Path(video_path)
    if not p.exists():
        raise FileNotFoundError(f"Fichier vidéo introuvable: {p}")

    # Si publish_at est utilisé, il est recommandé d'envoyer privacy_status=private.
    if publish_at and privacy_status.lower() != "private":
        logger.warning(
            "publish_at fourni, forçage de privacy_status=private pour une planification correcte."
        )
        privacy_status = "private"

    # Sanitize langues
    san_default_language = _sanitize_language(default_language)
    san_default_audio_language = _sanitize_language(default_audio_language)

    # Sanitize publish_at / recording_date
    if publish_at:
        publish_at = _ensure_future_publish_at(publish_at)
    if recording_date:
        recording_date = _to_rfc3339_utc(recording_date) or recording_date

    # Sanitize tags (trim, drop vides, limiter à 20)
    san_tags: list[str] = []
    if tags:
        for t in list(tags):
            if t is None:
                continue
            tt = str(t).strip()
            if not tt:
                continue
            # Limiter la longueur d'un tag individuel à 100
            san_tags.append(tt[:100])
            if len(san_tags) >= 20:
                break

    body = {
        "snippet": {
            "title": title,
            "description": description or "",
            "tags": san_tags,
            "categoryId": str(category_id),
        },
        "status": {
            "privacyStatus": privacy_status,
        },
    }
    if san_default_language:
        body["snippet"]["defaultLanguage"] = san_default_language
    if san_default_audio_language:
        body["snippet"]["defaultAudioLanguage"] = san_default_audio_language
    if embeddable is not None:
        body["status"]["embeddable"] = bool(embeddable)
    if license:
        body["status"]["license"] = license  # "youtube" ou "creativeCommon"
    if public_stats_viewable is not None:
        body["status"]["publicStatsViewable"] = bool(public_stats_viewable)
    if publish_at:
        body["status"]["publishAt"] = publish_at  # RFC3339 UTC
    if made_for_kids is not None:
        body["status"]["madeForKids"] = bool(made_for_kids)
    if recording_date:
        body["recordingDetails"] = {"recordingDate": recording_date}

    # Log minimal du corps envoyé pour diagnostiquer INVALID_REQUEST_METADATA
    try:
        logger.info("Upload body: %s", json.dumps(body, ensure_ascii=False))
    except Exception:
        logger.info("Upload body (repr): %r", body)

    media = MediaFileUpload(str(p), chunksize=-1, resumable=True)
    parts = ["snippet", "status"]
    if "recordingDetails" in body:
        parts.append("recordingDetails")
    request = service.videos().insert(part=",".join(parts), body=body, media_body=media)

    response = _resumable_upload_with_retry(request)
    video_id = response.get("id")
    logger.info("Upload terminé. Video ID: %s", video_id)

    if thumbnail_path:
        _set_thumbnail(service, video_id, thumbnail_path)

    return response


def _resumable_upload_with_retry(request, max_retries: int = 8) -> dict:
    # Voir: https://developers.google.com/youtube/v3/guides/using_resumable_uploads
    retries = 0
    response = None
    while response is None:
        error = None
        try:
            status, response = request.next_chunk()
            if status:
                logger.info(
                    "Progression upload: %.2f%%", float(status.progress()) * 100
                )
        except HttpError as e:
            if e.resp is not None:
                status_code = getattr(e.resp, "status", None)
            else:
                status_code = None
            if status_code in {500, 502, 503, 504}:
                error = f"Erreur serveur {status_code}, tentative de reprise..."
            else:
                # Erreurs non récupérables (ex: 400, 401, 403, etc.)
                raise
        except Exception as e:  # p.ex. erreurs réseau
            error = f"Exception durant l'upload: {e}"

        if error:
            logger.warning(error)
            retries += 1
            if retries > max_retries:
                raise RuntimeError("Nombre maximal de tentatives atteint pour l'upload")
            sleep = _exponential_backoff(retries)
            logger.info("Nouvelle tentative dans %.1fs", sleep)
            time.sleep(sleep)
    return response


def _exponential_backoff(retry_count: int) -> float:
    # Backoff exponentiel avec jitter (base 2)
    max_sleep = min(60, (2**retry_count))
    return random.uniform(1, max_sleep)


def _set_thumbnail(service, video_id: str, thumbnail_path: str | Path) -> None:
    tp = Path(thumbnail_path)
    if not tp.exists():
        logger.warning("Thumbnail introuvable: %s (ignoré)", tp)
        return
    media = MediaFileUpload(str(tp), resumable=False)
    try:
        service.thumbnails().set(videoId=video_id, media_body=media).execute()
        logger.info("Miniature définie pour la vidéo %s", video_id)
    except HttpError as e:
        logger.error("Échec de définition de la miniature: %s", e)
