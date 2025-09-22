from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


def generate_thumbnail(
    video_path: str | Path, 
    output_path: str | Path,
    timestamp: str = "00:00:05",
    width: int = 1280,
    height: int = 720,
    quality: int = 2
) -> bool:
    """
    Génère une thumbnail à partir d'une frame vidéo avec ffmpeg.
    
    Args:
        video_path: Chemin vers la vidéo source
        output_path: Chemin de sortie pour la thumbnail (.jpg)
        timestamp: Timestamp de la frame à extraire (format HH:MM:SS)
        width: Largeur de la thumbnail
        height: Hauteur de la thumbnail  
        quality: Qualité JPEG (1=meilleure, 31=pire)
    
    Returns:
        True si succès, False sinon
    """
    try:
        video_path = Path(video_path)
        output_path = Path(output_path)
        
        if not video_path.exists():
            log.error(f"Vidéo source introuvable: {video_path}")
            return False
            
        # Créer le dossier de sortie si nécessaire
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Commande ffmpeg pour extraire une frame
        cmd = [
            "ffmpeg",
            "-y",  # Overwrite output
            "-i", str(video_path),
            "-ss", timestamp,  # Seek to timestamp
            "-vframes", "1",  # Extract 1 frame
            "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black",
            "-q:v", str(quality),  # JPEG quality
            str(output_path)
        ]
        
        log.info(f"Génération thumbnail: {video_path} -> {output_path} à {timestamp}")
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0:
            if output_path.exists():
                log.info(f"Thumbnail générée: {output_path} ({output_path.stat().st_size} bytes)")
                return True
            else:
                log.error("ffmpeg a réussi mais le fichier thumbnail n'existe pas")
                return False
        else:
            log.error(f"Erreur ffmpeg: {result.stderr}")
            return False
            
    except subprocess.TimeoutExpired:
        log.error("Timeout lors de la génération de thumbnail")
        return False
    except Exception as e:
        log.error(f"Erreur lors de la génération de thumbnail: {e}")
        return False


def generate_multiple_thumbnails(
    video_path: str | Path,
    output_dir: str | Path,
    timestamps: list[str] = None,
    prefix: str = "thumb"
) -> list[Path]:
    """
    Génère plusieurs thumbnails à différents timestamps.
    
    Args:
        video_path: Chemin vers la vidéo source
        output_dir: Dossier de sortie
        timestamps: Liste de timestamps (défaut: 5s, 25%, 50%, 75%)
        prefix: Préfixe des fichiers générés
    
    Returns:
        Liste des chemins des thumbnails générées avec succès
    """
    if timestamps is None:
        timestamps = ["00:00:05", "25%", "50%", "75%"]
    
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    generated = []
    
    for i, timestamp in enumerate(timestamps):
        output_path = output_dir / f"{prefix}_{i+1}.jpg"
        if generate_thumbnail(video_path, output_path, timestamp):
            generated.append(output_path)
    
    return generated


def get_best_thumbnail(video_path: str | Path, output_path: str | Path) -> Optional[Path]:
    """
    Génère la meilleure thumbnail automatiquement (frame à 30% de la vidéo).
    
    Args:
        video_path: Chemin vers la vidéo source
        output_path: Chemin de sortie pour la thumbnail
    
    Returns:
        Chemin de la thumbnail générée ou None si échec
    """
    if generate_thumbnail(video_path, output_path, timestamp="30%"):
        return Path(output_path)
    
    # Fallback: essayer à 5 secondes
    log.warning("Échec thumbnail à 30%, tentative à 5s")
    if generate_thumbnail(video_path, output_path, timestamp="00:00:05"):
        return Path(output_path)
    
    return None
