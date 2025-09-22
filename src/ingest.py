from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from yt_dlp import YoutubeDL


class IngestError(Exception):
    pass


def download_source(
    url: str,
    *,
    output_dir: str | Path = "downloads",
    filename: Optional[str] = None,
    prefer_ext: str = "mp4",
) -> Path:
    """
    Télécharge une vidéo (YouTube/autres) avec yt-dlp et renvoie le chemin du fichier résultant.

    - Utilise le meilleur flux vidéo+audio disponible et convertit/merge en mp4 si possible (requiert ffmpeg).
    - output_dir est créé si nécessaire.
    - filename (sans extension) peut être forcé; sinon, un modèle titre-id est utilisé.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if filename:
        out_tmpl = str(out_dir / f"{filename}.%(ext)s")
    else:
        # Exemple: downloads/MonTitre-<id>.ext
        out_tmpl = str(out_dir / "%(title)s-%(id)s.%(ext)s")

    ydl_opts = {
        # "bv*+ba/b" => meilleure vidéo + meilleur audio sinon meilleur unique
        "format": "bv*+ba/b",
        "outtmpl": out_tmpl,
        # Post-processing: convertit en mp4 si possible
        "postprocessors": [
            {
                "key": "FFmpegVideoConvertor",
                "preferedformat": prefer_ext,
            }
        ],
        "merge_output_format": prefer_ext,
        "noprogress": True,
        "quiet": True,
        "no_warnings": True,
    }

    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            # yt-dlp renvoie le chemin final via prepare_filename avant postproc; on recompose
            final_basename = ydl.prepare_filename(info)
        # Remplace extension par prefer_ext si conversion
        final_path = Path(final_basename).with_suffix(f".{prefer_ext}")
        if not final_path.exists():
            # si pas converti, garde l'original
            final_path = Path(final_basename)
        return final_path.resolve()
    except Exception as e:
        raise IngestError(f"Échec du téléchargement: {e}")
