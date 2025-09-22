from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from moviepy.editor import (
    VideoFileClip,
    concatenate_videoclips,
    CompositeAudioClip,
    AudioFileClip,
)
from moviepy import vfx, afx


class EditError(Exception):
    pass


def _parse_resize(resize: Optional[str]) -> Optional[Tuple[int, int]]:
    if not resize:
        return None
    if "x" in resize:
        w, h = resize.lower().split("x", 1)
        return int(w), int(h)
    raise EditError("Format de --resize invalide. Utilisez WIDTHxHEIGHT, ex: 1920x1080")


def simple_edit(
    inputs: Iterable[str | Path],
    output: str | Path,
    *,
    start: Optional[float] = None,
    end: Optional[float] = None,
    concat_inputs: bool = False,
    resize: Optional[str] = None,  # WIDTHxHEIGHT
    speed: float = 1.0,
    music_path: Optional[str | Path] = None,
    music_volume: float = 0.2,
    fadein: float = 0.0,
    fadeout: float = 0.0,
) -> Path:
    """
    Réalise un montage simple:
    - Trim (start/end) sur chaque clip d'entrée
    - Concaténation (si concat_inputs=True)
    - Redimensionnement (WIDTHxHEIGHT)
    - Changement de vitesse (speed)
    - Ajout d'une musique de fond (volume réglable)
    - Fade-in / Fade-out audio-vidéo
    """
    input_paths = [Path(p) for p in inputs]
    if not input_paths:
        raise EditError("Aucun clip d'entrée fourni")
    for p in input_paths:
        if not p.exists():
            raise EditError(f"Fichier introuvable: {p}")

    resize_wh = _parse_resize(resize)

    clips: List[VideoFileClip] = []
    try:
        # Charger et préparer chaque clip
        for p in input_paths:
            c = VideoFileClip(str(p))
            if start is not None or end is not None:
                c = c.subclip(start if start is not None else 0, end)
            if resize_wh:
                c = c.resize(newsize=resize_wh)
            if speed and speed != 1.0:
                c = c.fx(vfx.speedx, speed)
            clips.append(c)

        # Concaténation ou clip unique
        if concat_inputs and len(clips) > 1:
            final = concatenate_videoclips(clips, method="compose")
        else:
            final = clips[0]

        # Fade video
        if fadein and fadein > 0:
            final = final.fx(vfx.fadein, fadein)
        if fadeout and fadeout > 0:
            final = final.fx(vfx.fadeout, fadeout)

        # Audio et musique de fond
        base_audio = final.audio
        if music_path:
            mpath = Path(music_path)
            if not mpath.exists():
                raise EditError(f"Musique introuvable: {mpath}")
            bgm = AudioFileClip(str(mpath))
            if fadein and fadein > 0:
                bgm = bgm.fx(afx.audio_fadein, fadein)
            if fadeout and fadeout > 0:
                bgm = bgm.fx(afx.audio_fadeout, fadeout)
            # Ajuste la durée de la musique à la vidéo
            if bgm.duration > final.duration:
                bgm = bgm.subclip(0, final.duration)
            audio_tracks = []
            if base_audio is not None:
                audio_tracks.append(base_audio)
            audio_tracks.append(bgm.volumex(music_volume))
            final = final.set_audio(CompositeAudioClip(audio_tracks))

        outp = Path(output)
        outp.parent.mkdir(parents=True, exist_ok=True)
        # moviepy choisit le codec selon extension; mp4 => 'libx264' généralement
        final.write_videofile(
            str(outp),
            codec="libx264",
            audio_codec="aac",
            threads=2,
            verbose=False,
            logger=None,
        )
        return outp.resolve()
    finally:
        # Libère correctement les ressources
        for c in clips:
            try:
                c.close()
            except Exception:
                pass
