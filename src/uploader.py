from __future__ import annotations

import logging
import random
import time
from pathlib import Path
from typing import Iterable, Optional

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload


logger = logging.getLogger(__name__)


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

    body = {
        "snippet": {
            "title": title,
            "description": description or "",
            "tags": list(tags) if tags else [],
            "categoryId": str(category_id),
        },
        "status": {
            "privacyStatus": privacy_status,
        },
    }
    if default_language:
        body["snippet"]["defaultLanguage"] = default_language
    if default_audio_language:
        body["snippet"]["defaultAudioLanguage"] = default_audio_language
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
