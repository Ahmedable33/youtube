"""
Générateur de sous-titres automatique avec Whisper
Supporte la détection automatique de langue et la traduction multilingue
"""

import logging
import subprocess
from pathlib import Path
from typing import Optional, List, Dict, Any
import json
import tempfile
import os

log = logging.getLogger(__name__)

class SubtitleError(Exception):
    """Erreur lors de la génération de sous-titres"""
    pass

def is_whisper_available() -> bool:
    """Vérifie si Whisper est installé et disponible"""
    try:
        result = subprocess.run(
            ["whisper", "--help"], 
            capture_output=True, 
            text=True, 
            timeout=10
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False

def detect_language(video_path: Path, model: str = "base") -> Optional[str]:
    """
    Détecte la langue principale de la vidéo
    
    Args:
        video_path: Chemin vers la vidéo
        model: Modèle Whisper à utiliser (tiny, base, small, medium, large)
        
    Returns:
        Code langue ISO (ex: 'fr', 'en') ou None si échec
    """
    if not video_path.exists():
        raise SubtitleError(f"Vidéo introuvable: {video_path}")
    
    if not is_whisper_available():
        raise SubtitleError("Whisper n'est pas installé. Installez avec: pip install openai-whisper")
    
    try:
        # Utiliser Whisper pour détecter la langue sur les 30 premières secondes
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_audio = Path(temp_dir) / "audio_sample.wav"
            
            # Extraire un échantillon audio de 30s pour la détection
            cmd = [
                "ffmpeg", "-i", str(video_path),
                "-t", "30",  # 30 secondes
                "-vn",  # Pas de vidéo
                "-acodec", "pcm_s16le",
                "-ar", "16000",  # Sample rate pour Whisper
                "-ac", "1",  # Mono
                "-y",  # Overwrite
                str(temp_audio)
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode != 0:
                log.warning("Échec extraction audio pour détection langue: %s", result.stderr)
                return None
            
            # Détecter la langue avec Whisper
            cmd = [
                "whisper", str(temp_audio),
                "--model", model,
                "--language", "auto",
                "--output_format", "json",
                "--output_dir", temp_dir
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.returncode != 0:
                log.warning("Échec détection langue Whisper: %s", result.stderr)
                return None
            
            # Lire le résultat JSON
            json_file = temp_audio.with_suffix('.json')
            if json_file.exists():
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get('language')
            
            return None
            
    except subprocess.TimeoutExpired:
        raise SubtitleError("Timeout lors de la détection de langue")
    except Exception as e:
        raise SubtitleError(f"Erreur détection langue: {e}")

def generate_subtitles(
    video_path: Path,
    output_path: Path,
    language: Optional[str] = None,
    model: str = "base",
    translate_to_english: bool = False
) -> Path:
    """
    Génère des sous-titres SRT pour une vidéo
    
    Args:
        video_path: Chemin vers la vidéo
        output_path: Chemin de sortie pour le fichier .srt
        language: Langue source (auto-détection si None)
        model: Modèle Whisper (tiny, base, small, medium, large)
        translate_to_english: Traduire vers l'anglais
        
    Returns:
        Chemin vers le fichier .srt généré
    """
    if not video_path.exists():
        raise SubtitleError(f"Vidéo introuvable: {video_path}")
    
    if not is_whisper_available():
        raise SubtitleError("Whisper n'est pas installé. Installez avec: pip install openai-whisper")
    
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        cmd = [
            "whisper", str(video_path),
            "--model", model,
            "--output_format", "srt",
            "--output_dir", str(output_path.parent)
        ]
        
        # Langue spécifique ou auto-détection
        if language:
            cmd.extend(["--language", language])
        
        # Traduction vers l'anglais
        if translate_to_english:
            cmd.append("--task")
            cmd.append("translate")
        
        log.info("Génération sous-titres: %s", " ".join(cmd))
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)  # 10 min max
        
        if result.returncode != 0:
            raise SubtitleError(f"Échec génération Whisper: {result.stderr}")
        
        # Whisper génère automatiquement le nom de fichier
        expected_srt = output_path.parent / f"{video_path.stem}.srt"
        
        if expected_srt.exists():
            # Renommer vers le nom souhaité si différent
            if expected_srt != output_path:
                expected_srt.rename(output_path)
            return output_path
        else:
            raise SubtitleError(f"Fichier SRT non trouvé après génération: {expected_srt}")
            
    except subprocess.TimeoutExpired:
        raise SubtitleError("Timeout lors de la génération de sous-titres (>10min)")
    except Exception as e:
        raise SubtitleError(f"Erreur génération sous-titres: {e}")

def generate_multilingual_subtitles(
    video_path: Path,
    output_dir: Path,
    languages: List[str],
    model: str = "base",
    source_language: Optional[str] = None
) -> Dict[str, Path]:
    """
    Génère des sous-titres en plusieurs langues
    
    Args:
        video_path: Chemin vers la vidéo
        output_dir: Dossier de sortie
        languages: Liste des codes langues (ex: ['fr', 'en', 'es'])
        model: Modèle Whisper
        source_language: Langue source (auto-détection si None)
        
    Returns:
        Dictionnaire {langue: chemin_srt}
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    results = {}
    
    # Détecter la langue source si non spécifiée
    if not source_language:
        try:
            source_language = detect_language(video_path, model)
            log.info("Langue détectée: %s", source_language)
        except Exception as e:
            log.warning("Impossible de détecter la langue: %s", e)
            source_language = "auto"
    
    for lang in languages:
        try:
            srt_path = output_dir / f"{video_path.stem}_{lang}.srt"
            
            if lang == source_language:
                # Transcription dans la langue originale
                generated = generate_subtitles(
                    video_path, srt_path, language=source_language, model=model
                )
            elif lang == "en":
                # Traduction vers l'anglais (supportée nativement par Whisper)
                generated = generate_subtitles(
                    video_path, srt_path, language=source_language, 
                    model=model, translate_to_english=True
                )
            else:
                # Pour les autres langues, générer d'abord en anglais puis utiliser un traducteur
                # (nécessiterait une intégration avec Google Translate ou similaire)
                log.warning("Traduction vers %s non supportée directement. Utilisez un service de traduction externe.", lang)
                continue
            
            results[lang] = generated
            log.info("Sous-titres générés pour %s: %s", lang, generated)
            
        except Exception as e:
            log.error("Échec génération sous-titres %s: %s", lang, e)
    
    return results

def validate_srt_file(srt_path: Path) -> bool:
    """
    Valide la structure d'un fichier SRT
    
    Args:
        srt_path: Chemin vers le fichier .srt
        
    Returns:
        True si le fichier est valide
    """
    if not srt_path.exists():
        return False
    
    try:
        with open(srt_path, 'r', encoding='utf-8') as f:
            content = f.read().strip()
        
        if not content:
            return False
        
        # Vérification basique: doit contenir des numéros de séquence et des timestamps
        lines = content.split('\n')
        has_sequence = False
        has_timestamp = False
        
        for line in lines:
            line = line.strip()
            if line.isdigit():
                has_sequence = True
            if '-->' in line:
                has_timestamp = True
        
        return has_sequence and has_timestamp
        
    except Exception as e:
        log.error("Erreur validation SRT %s: %s", srt_path, e)
        return False

def get_subtitle_info(srt_path: Path) -> Dict[str, Any]:
    """
    Extrait des informations d'un fichier SRT
    
    Returns:
        Dictionnaire avec duration, subtitle_count, etc.
    """
    if not validate_srt_file(srt_path):
        return {}
    
    try:
        with open(srt_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Compter les sous-titres
        subtitle_count = content.count('\n\n') + 1
        
        # Extraire la durée (dernier timestamp)
        timestamps = []
        for line in content.split('\n'):
            if '-->' in line:
                # Format: 00:00:01,000 --> 00:00:03,500
                end_time = line.split('-->')[1].strip()
                timestamps.append(end_time)
        
        duration = timestamps[-1] if timestamps else "00:00:00,000"
        
        return {
            "subtitle_count": subtitle_count,
            "duration": duration,
            "file_size": srt_path.stat().st_size,
            "valid": True
        }
        
    except Exception as e:
        log.error("Erreur extraction info SRT %s: %s", srt_path, e)
        return {"valid": False, "error": str(e)}
