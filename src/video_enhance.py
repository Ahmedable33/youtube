from __future__ import annotations

import logging
import re
import shutil
import subprocess
import time
from collections import deque
from pathlib import Path
from typing import Optional, Union


def _infer_target_height(scale: Optional[str]) -> Optional[int]:
    """Retourne une hauteur cible si déductible depuis l'option scale."""
    if not scale:
        return None
    s = scale.strip().lower()
    if s.endswith("p") and s[:-1].isdigit():
        return int(s[:-1])
    if "x" in s and s.count("x") == 1:
        w, h = s.split("x", 1)
        if h.isdigit():
            return int(h)
    return None


def _default_bitrate_for_height(h: Optional[int], codec: str) -> str:
    """Heuristique simple pour choisir un bitrate par défaut.

    Valeurs approximatives adaptées à YouTube:
    - <=720p: 4M (H.264), 3M (HEVC)
    - 1080p: 8M (H.264), 6M (HEVC)
    - 1440p: 12M (H.264), 10M (HEVC)
    - 2160p+: 20M (H.264), 16M (HEVC)
    """
    c = codec.lower()
    if h is None or h <= 720:
        return "3M" if c == "hevc" else "4M"
    if h <= 1080:
        return "6M" if c == "hevc" else "8M"
    if h <= 1440:
        return "10M" if c == "hevc" else "12M"
    return "16M" if c == "hevc" else "20M"


class EnhanceError(Exception):
    pass


_PRESET_CHOICES = {
    "ultrafast",
    "superfast",
    "veryfast",
    "faster",
    "fast",
    "medium",
    "slow",
    "slower",
    "veryslow",
}


_DURATION_RE = re.compile(r"Duration: (\d{2}):(\d{2}):(\d{2})[\.,](\d{2})")
_TIME_RE = re.compile(r"time=(\d{2}):(\d{2}):(\d{2})[\.,](\d{2})")


def _hms_to_seconds(h: str, m: str, s: str, cs: str) -> float:
    """Convertit HH:MM:SS.cc en secondes (cc = centi ou milli tronqué)."""
    return int(h) * 3600 + int(m) * 60 + int(s) + int(cs) / 100.0


def _parse_scale_arg(scale: Optional[str]) -> Optional[str]:
    """
    Convertit l'argument --scale en expression de filtre ffmpeg 'scale='.
    Retourne une chaîne à insérer dans -vf (sans le préfixe 'scale='), ou None.

    Exemples d'entrée:
    - "1080p" => "-2:1080:flags=lanczos"
    - "2160p" => "-2:2160:flags=lanczos"
    - "1920x1080" => "1920:1080:flags=lanczos"
    - "2x" => "iw*2:ih*2:flags=lanczos"
    - "1.5x" => "iw*1.5:ih*1.5:flags=lanczos"
    """
    if not scale:
        return None
    s = scale.strip().lower()
    if s.endswith("p") and s[:-1].isdigit():
        # hauteur cible, largeur auto pair
        h = int(s[:-1])
        return f"-2:{h}:flags=lanczos"
    if "x" in s and s.count("x") == 1:
        # WIDTHxHEIGHT
        w, h = s.split("x", 1)
        if w.isdigit() and h.isdigit():
            return f"{int(w)}:{int(h)}:flags=lanczos"
    if s.endswith("x"):
        # facteur *x
        factor_str = s[:-1]
        try:
            factor = float(factor_str)
            # Expressions dynamiques basées sur la taille d'entrée
            # Utilise les expressions iw/ih
            # Remarque: ffmpeg demande souvent des dimensions paires, lanczos aide, mais
            # on pourrait forcer trunc(iw*factor/2)*2, toutefois cela alourdit l'expression.
            return f"iw*{factor}:ih*{factor}:flags=lanczos"
        except Exception:
            pass
    raise EnhanceError(
        "Format de --scale invalide. Utilisez 720p|1080p|1440p|2160p|WIDTHxHEIGHT|1.5x|2x"
    )


def enhance_video(
    *,
    input_path: Union[str, Path],
    output_path: Union[str, Path],
    codec: str = "h264",
    hwaccel: str = "none",
    scale: Optional[str] = None,
    fps: Optional[float] = None,
    denoise: bool = False,
    sharpen: bool = False,
    deinterlace: bool = False,
    color_fix: bool = False,
    deband: bool = False,
    deblock: bool = False,
    sharpen_amount: Optional[float] = None,
    contrast: Optional[float] = None,
    saturation: Optional[float] = None,
    crf: int = 18,
    bitrate: Optional[str] = None,
    preset: str = "medium",
    reencode_audio: bool = False,
    loudnorm: bool = False,
    audio_bitrate: str = "192k",
) -> Path:
    """
    Améliore la qualité de la vidéo en utilisant ffmpeg via subprocess.

    - Upscale (scale): 720p/1080p/1440p/2160p, WIDTHxHEIGHT, ou facteur (ex: 2x)
    - Denoise: hqdn3d
    - Sharpen: unsharp
    - Deinterlace: yadif
    - Correction légère couleurs: eq (contrast/saturation)
    - FPS: filtre fps

    Encode en H.264 (libx264) avec CRF/preset (ou bitrate constant si fourni).
    """
    log = logging.getLogger("video_enhance")

    in_path = Path(input_path)
    out_path = Path(output_path)
    if not in_path.exists():
        raise EnhanceError(f"Fichier d'entrée introuvable: {in_path}")

    # Vérifier ffmpeg
    if not shutil.which("ffmpeg"):
        raise EnhanceError(
            "ffmpeg introuvable dans le PATH. Installez-le (ex: brew install ffmpeg)"
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Construire la chaîne de filtres vidéo
    vf_parts: list[str] = []

    # Désentrelacement d'abord si demandé
    if deinterlace:
        vf_parts.append("yadif=1")

    # Mise à l'échelle
    scale_expr = _parse_scale_arg(scale)
    if scale_expr:
        vf_parts.append(f"scale={scale_expr}")

    # Denoise (hqdn3d): valeurs modérées
    if denoise:
        vf_parts.append("hqdn3d=1.5:1.5:6:6")

    # Debanding (réduction banding) via gradfun
    if deband:
        # valeurs modérées
        vf_parts.append("gradfun=20:30")

    # Deblock (réduction macroblocs)
    if deblock:
        # alpha/beta modérés
        vf_parts.append("deblock=alpha=0.5:beta=0.5")

    # Sharpen (unsharp): légère à forte selon sharpen_amount
    if sharpen or (sharpen_amount is not None):
        amt = (
            0.8
            if sharpen_amount is None
            else max(0.0, min(1.5, float(sharpen_amount) * 1.5))
        )
        vf_parts.append(f"unsharp=5:5:{amt}:5:5:0.0")

    # Correction colorimétrique
    if contrast is not None or saturation is not None:
        c = float(contrast) if contrast is not None else 1.0
        s = float(saturation) if saturation is not None else 1.0
        vf_parts.append(f"eq=contrast={c}:saturation={s}")
    elif color_fix:
        vf_parts.append("eq=contrast=1.05:saturation=1.10")

    # FPS en fin de chaîne
    if fps and fps > 0:
        vf_parts.append(f"fps={fps}")

    # Commande ffmpeg
    cmd: list[str] = [
        "ffmpeg",
        "-y",  # overwrite
        "-hide_banner",
        "-i",
        str(in_path),
    ]

    if vf_parts:
        cmd += ["-vf", ",".join(vf_parts)]

    # Codec vidéo et qualité
    c = (codec or "h264").lower()
    acc = (hwaccel or "none").lower()
    if c == "h264":
        if acc == "videotoolbox":
            cmd += ["-c:v", "h264_videotoolbox"]
            if bitrate:
                cmd += ["-b:v", bitrate]
            else:
                # videotoolbox ne supporte pas -q:v pour h264: choisir un bitrate par défaut
                target_h = _infer_target_height(scale)
                auto_br = _default_bitrate_for_height(target_h, "h264")
                cmd += ["-b:v", auto_br]
        else:
            cmd += [
                "-c:v",
                "libx264",
                "-preset",
                preset if preset in _PRESET_CHOICES else "medium",
            ]
            if bitrate:
                cmd += ["-b:v", bitrate, "-maxrate", bitrate, "-bufsize", "2M"]
            else:
                cmd += ["-crf", str(crf)]
    elif c == "hevc":
        if acc == "videotoolbox":
            cmd += ["-c:v", "hevc_videotoolbox"]
            if bitrate:
                cmd += ["-b:v", bitrate]
            else:
                # Préférer un bitrate par défaut en mode matériel
                target_h = _infer_target_height(scale)
                auto_br = _default_bitrate_for_height(target_h, "hevc")
                cmd += ["-b:v", auto_br]
            cmd += ["-tag:v", "hvc1"]
        else:
            # H.265/HEVC
            cmd += [
                "-c:v",
                "libx265",
                "-preset",
                preset if preset in _PRESET_CHOICES else "medium",
            ]
            if bitrate:
                cmd += ["-b:v", bitrate]
            else:
                cmd += ["-crf", str(crf)]
            cmd += ["-tag:v", "hvc1"]  # meilleure compatibilité mp4
    elif c == "vp9":
        # VP9
        cmd += ["-c:v", "libvpx-vp9", "-row-mt", "1"]
        # map simple du preset vers cpu-used (plus élevé = plus rapide/moins efficace)
        preset_map = {
            "ultrafast": "8",
            "superfast": "7",
            "veryfast": "6",
            "faster": "5",
            "fast": "4",
            "medium": "3",
            "slow": "2",
            "slower": "1",
            "veryslow": "0",
        }
        cpu = preset_map.get(preset if preset in _PRESET_CHOICES else "medium", "3")
        cmd += ["-cpu-used", cpu]
        if bitrate:
            cmd += ["-b:v", bitrate]
        else:
            cmd += ["-crf", str(crf), "-b:v", "0"]
    elif c == "av1":
        # AV1 (libaom-av1)
        cmd += ["-c:v", "libaom-av1"]
        preset_map = {
            "ultrafast": "8",
            "superfast": "7",
            "veryfast": "6",
            "faster": "5",
            "fast": "4",
            "medium": "3",
            "slow": "2",
            "slower": "1",
            "veryslow": "0",
        }
        cpu = preset_map.get(preset if preset in _PRESET_CHOICES else "medium", "3")
        cmd += ["-cpu-used", cpu]
        if bitrate:
            cmd += ["-b:v", bitrate]
        else:
            cmd += ["-crf", str(crf), "-b:v", "0"]
    else:
        raise EnhanceError("Codec non supporté: " + c)

    # format de pixel compatible players
    cmd += ["-pix_fmt", "yuv420p"]

    # Audio / Loudness normalization
    afilters = []
    if loudnorm:
        # EBU R128 loudness normalization
        afilters.append("loudnorm=I=-23:TP=-2:LRA=7")
        reencode_audio = True  # nécessaire pour appliquer le filtre

    if afilters:
        cmd += ["-af", ",".join(afilters)]

    if reencode_audio:
        cmd += ["-c:a", "aac", "-b:a", audio_bitrate]
    else:
        cmd += ["-c:a", "copy"]

    # Optimisation streaming
    cmd += ["-movflags", "+faststart"]

    cmd += [str(out_path)]

    log.debug("Commande ffmpeg: %s", " ".join(cmd))

    try:
        # Lecture en streaming de stderr pour progression
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        total_seconds: Optional[float] = None
        last_log = 0.0
        tail = deque(maxlen=50)

        assert proc.stderr is not None
        for line in proc.stderr:
            tail.append(line.rstrip())
            # Détecter la durée totale (une seule fois)
            if total_seconds is None:
                m = _DURATION_RE.search(line)
                if m:
                    total_seconds = _hms_to_seconds(*m.groups())
            # Extraire time courant
            mt = _TIME_RE.search(line)
            if mt and total_seconds and total_seconds > 0:
                cur = _hms_to_seconds(*mt.groups())
                pct = max(0.0, min(100.0, (cur / total_seconds) * 100.0))
                now = time.time()
                if now - last_log >= 1.0:
                    rem = max(0.0, total_seconds - cur)
                    # ETA approximatif (en sec) faute de vitesse instantanée
                    log.info(
                        "Progression ffmpeg: %.1f%% (t=%s, ETA~%.0fs)",
                        pct,
                        mt.group(0)[5:],
                        rem,
                    )
                    last_log = now

        proc.stdout.read() if proc.stdout else ""
        ret = proc.wait()
        if ret != 0:
            raise EnhanceError("ffmpeg a échoué:\n" + "\n".join(tail))
    except FileNotFoundError:
        raise EnhanceError("ffmpeg introuvable (commande non trouvée)")

    return out_path.resolve()
