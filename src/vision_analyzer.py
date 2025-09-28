"""
Analyseur de contenu vidéo par IA Vision
Extrait des frames et analyse le contenu pour détecter automatiquement:
- Catégorie YouTube appropriée
- Tags pertinents basés sur le contenu visuel
- Type de contenu (gaming, éducation, musique, etc.)
"""

import logging
import tempfile
import subprocess
from pathlib import Path
from typing import List, Dict, Optional
import base64
import json
from datetime import datetime

log = logging.getLogger(__name__)


class VisionAnalyzer:
    """Analyseur de contenu vidéo par IA Vision"""

    # Mapping des catégories détectées vers les IDs YouTube
    CATEGORY_MAPPING = {
        "gaming": 20,
        "games": 20,
        "videogames": 20,
        "esports": 20,
        "education": 27,
        "tutorial": 27,
        "learning": 27,
        "course": 27,
        "entertainment": 24,
        "comedy": 23,
        "funny": 23,
        "humor": 23,
        "music": 10,
        "song": 10,
        "concert": 10,
        "instrument": 10,
        "technology": 28,
        "tech": 28,
        "science": 28,
        "programming": 28,
        "coding": 28,
        "news": 25,
        "politics": 25,
        "current events": 25,
        "sports": 17,
        "football": 17,
        "basketball": 17,
        "soccer": 17,
        "fitness": 17,
        "workout": 17,
        "howto": 26,
        "diy": 26,
        "tutorial": 26,
        "guide": 26,
        "recipe": 26,
        "cooking": 26,
        "travel": 19,
        "vlog": 22,
        "lifestyle": 22,
        "personal": 22,
        "daily": 22,
        "pets": 15,
        "animals": 15,
        "cats": 15,
        "dogs": 15,
        "nature": 15,
        "cars": 2,
        "automotive": 2,
        "vehicles": 2,
        "film": 1,
        "movie": 1,
        "cinema": 1,
        "trailer": 1,
    }

    def __init__(self, provider: str = "openai", config: Optional[Dict] = None):
        """
        Initialiser l'analyseur

        Args:
            provider: Provider IA à utiliser ("openai", "google", "ollama")
            config: Configuration spécifique au provider
        """
        self.provider = provider.lower()
        self.config = config or {}

        # Vérifier la disponibilité du provider
        if self.provider == "openai":
            self._init_openai()
        elif self.provider == "google":
            self._init_google()
        elif self.provider == "ollama":
            self._init_ollama()
        else:
            raise ValueError(f"Provider non supporté: {provider}")

    def _init_openai(self):
        """Initialiser OpenAI Vision"""
        try:
            import openai

            self.client = openai.OpenAI(api_key=self.config.get("api_key"))
        except ImportError:
            raise ImportError("openai package requis pour le provider OpenAI")

    def _init_google(self):
        """Initialiser Google Vision"""
        try:
            from google.cloud import vision

            self.client = vision.ImageAnnotatorClient()
        except ImportError:
            raise ImportError(
                "google-cloud-vision package requis pour Google Vision")

    def _init_ollama(self):
        """Initialiser Ollama avec modèle vision"""
        self.model = self.config.get("model", "llava")
        self.base_url = self.config.get("base_url", "http://localhost:11434")

    def extract_frames(self, video_path: Path, num_frames: int = 5) -> List[Path]:
        """
        Extraire des frames représentatives de la vidéo

        Args:
            video_path: Chemin vers la vidéo
            num_frames: Nombre de frames à extraire

        Returns:
            Liste des chemins vers les frames extraites
        """
        if not video_path.exists():
            raise FileNotFoundError(f"Vidéo introuvable: {video_path}")

        # Créer un répertoire temporaire pour les frames
        temp_dir = Path(tempfile.mkdtemp(prefix="frames_"))
        frame_paths = []

        try:
            # Obtenir la durée de la vidéo
            duration_cmd = [
                "ffprobe",
                "-v",
                "quiet",
                "-show_entries",
                "format=duration",
                "-of",
                "csv=p=0",
                str(video_path),
            ]
            result = subprocess.run(
                duration_cmd, capture_output=True, text=True)

            if result.returncode != 0:
                raise RuntimeError(f"Erreur ffprobe: {result.stderr}")

            duration = float(result.stdout.strip())

            # Calculer les timestamps pour extraire les frames
            timestamps = []
            if num_frames == 1:
                timestamps = [duration / 2]  # Frame du milieu
            else:
                # Répartir uniformément sur la durée
                step = duration / (num_frames + 1)
                timestamps = [step * (i + 1) for i in range(num_frames)]

            # Extraire chaque frame
            for i, timestamp in enumerate(timestamps):
                frame_path = temp_dir / f"frame_{i:03d}.jpg"

                extract_cmd = [
                    "ffmpeg",
                    "-y",
                    "-v",
                    "quiet",
                    "-ss",
                    str(timestamp),
                    "-i",
                    str(video_path),
                    "-vframes",
                    "1",
                    "-q:v",
                    "2",  # Haute qualité
                    str(frame_path),
                ]

                result = subprocess.run(extract_cmd, capture_output=True)

                if result.returncode == 0 and frame_path.exists():
                    frame_paths.append(frame_path)
                    log.debug(
                        f"Frame extraite: {frame_path} (t={timestamp:.1f}s)")
                else:
                    log.warning(f"Échec extraction frame à t={timestamp:.1f}s")

            if not frame_paths:
                raise RuntimeError("Aucune frame n'a pu être extraite")

            log.info(
                f"Extraction réussie: {len(frame_paths)} frames de {video_path.name}"
            )
            return frame_paths

        except Exception as e:
            # Nettoyer en cas d'erreur
            for fp in frame_paths:
                try:
                    fp.unlink()
                except:
                    pass
            try:
                temp_dir.rmdir()
            except:
                pass
            raise e

    def analyze_frames(self, frame_paths: List[Path]) -> Dict:
        """
        Analyser les frames avec l'IA Vision

        Args:
            frame_paths: Liste des chemins vers les frames

        Returns:
            Dictionnaire avec l'analyse du contenu
        """
        if not frame_paths:
            raise ValueError("Aucune frame à analyser")

        if self.provider == "openai":
            return self._analyze_with_openai(frame_paths)
        elif self.provider == "google":
            return self._analyze_with_google(frame_paths)
        elif self.provider == "ollama":
            return self._analyze_with_ollama(frame_paths)
        else:
            raise ValueError(f"Provider non supporté: {self.provider}")

    def _analyze_with_openai(self, frame_paths: List[Path]) -> Dict:
        """Analyser avec OpenAI Vision"""
        try:
            # Préparer les images en base64
            images = []
            # Limiter à 3 frames pour les coûts
            for frame_path in frame_paths[:3]:
                with open(frame_path, "rb") as f:
                    image_data = base64.b64encode(f.read()).decode()
                    images.append(
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_data}",
                                "detail": "low",  # Réduire les coûts
                            },
                        }
                    )

            # Prompt pour l'analyse
            prompt = """Analyze these video frames and provide a JSON response with:
1. "content_type": main category (gaming, education, music, entertainment, technology, sports, etc.)
2. "tags": list of relevant tags (max 10)
3. "description": brief description of what you see
4. "confidence": confidence score 0-1

Focus on identifying the main subject, activity, and visual elements that would help categorize this content for YouTube."""

            messages = [
                {"role": "user", "content": [
                    {"type": "text", "text": prompt}, *images]}
            ]

            response = self.client.chat.completions.create(
                model="gpt-4-vision-preview",
                messages=messages,
                max_tokens=500,
                temperature=0.3,
            )

            # Parser la réponse JSON
            content = response.choices[0].message.content
            try:
                result = json.loads(content)
            except json.JSONDecodeError:
                # Fallback si pas de JSON valide
                result = {
                    "content_type": "entertainment",
                    "tags": ["video", "content"],
                    "description": content[:200],
                    "confidence": 0.5,
                }

            result["provider"] = "openai"
            result["analyzed_frames"] = len(frame_paths)
            return result

        except Exception as e:
            log.error(f"Erreur analyse OpenAI Vision: {e}")
            return self._fallback_analysis()

    def _analyze_with_google(self, frame_paths: List[Path]) -> Dict:
        """Analyser avec Google Vision"""
        try:
            from google.cloud import vision

            all_labels = []
            all_objects = []
            all_text = []

            # Analyser chaque frame
            for frame_path in frame_paths[:3]:  # Limiter pour les coûts
                with open(frame_path, "rb") as f:
                    content = f.read()

                image = vision.Image(content=content)

                # Détection d'objets et labels
                label_response = self.client.label_detection(image=image)
                object_response = self.client.object_localization(image=image)
                text_response = self.client.text_detection(image=image)

                # Collecter les résultats
                for label in label_response.label_annotations:
                    if label.score > 0.5:
                        all_labels.append(label.description.lower())

                for obj in object_response.localized_object_annotations:
                    if obj.score > 0.5:
                        all_objects.append(obj.name.lower())

                if text_response.text_annotations:
                    text = text_response.text_annotations[0].description
                    all_text.append(text.lower())

            # Analyser les résultats pour déterminer le type de contenu
            content_type = self._determine_content_type(
                all_labels + all_objects)
            tags = list(set(all_labels + all_objects))[:10]

            return {
                "content_type": content_type,
                "tags": tags,
                "description": f"Detected: {', '.join(tags[:5])}",
                "confidence": 0.8,
                "provider": "google",
                "analyzed_frames": len(frame_paths),
                "detected_text": all_text[:3] if all_text else [],
            }

        except Exception as e:
            log.error(f"Erreur analyse Google Vision: {e}")
            return self._fallback_analysis()

    def _analyze_with_ollama(self, frame_paths: List[Path]) -> Dict:
        """Analyser avec Ollama (llava)"""
        try:
            import requests

            # Prendre la première frame pour l'analyse
            frame_path = frame_paths[0]

            with open(frame_path, "rb") as f:
                image_data = base64.b64encode(f.read()).decode()

            prompt = """Analyze this video frame and respond with JSON format:
{
  "content_type": "main category like gaming, education, music, etc.",
  "tags": ["tag1", "tag2", "tag3"],
  "description": "brief description",
  "confidence": 0.8
}

Focus on identifying the main subject and activity shown."""

            payload = {
                "model": self.model,
                "prompt": prompt,
                "images": [image_data],
                "stream": False,
                "format": "json",
            }

            response = requests.post(
                f"{self.base_url}/api/generate", json=payload, timeout=60
            )

            if response.status_code == 200:
                result = response.json()
                content = result.get("response", "{}")

                try:
                    analysis = json.loads(content)
                    analysis["provider"] = "ollama"
                    analysis["analyzed_frames"] = len(frame_paths)
                    return analysis
                except json.JSONDecodeError:
                    pass

            return self._fallback_analysis()

        except Exception as e:
            log.error(f"Erreur analyse Ollama: {e}")
            return self._fallback_analysis()

    def _determine_content_type(self, labels: List[str]) -> str:
        """Déterminer le type de contenu basé sur les labels détectés"""
        label_text = " ".join(labels).lower()

        # Compter les occurrences de mots-clés par catégorie
        category_scores = {}

        for keyword, category_id in self.CATEGORY_MAPPING.items():
            if keyword in label_text:
                category_name = self._get_category_name(category_id)
                category_scores[category_name] = (
                    category_scores.get(category_name, 0) + 1
                )

        # Retourner la catégorie avec le plus d'occurrences
        if category_scores:
            return max(category_scores.items(), key=lambda x: x[1])[0]

        return "entertainment"  # Défaut

    def _get_category_name(self, category_id: int) -> str:
        """Obtenir le nom de catégorie à partir de l'ID"""
        category_names = {
            20: "gaming",
            27: "education",
            24: "entertainment",
            10: "music",
            28: "technology",
            25: "news",
            17: "sports",
            23: "comedy",
            26: "howto",
            22: "lifestyle",
            19: "travel",
            15: "pets",
            2: "automotive",
            1: "film",
        }
        return category_names.get(category_id, "entertainment")

    def _fallback_analysis(self) -> Dict:
        """Analyse de fallback en cas d'erreur"""
        return {
            "content_type": "entertainment",
            "tags": ["video", "content"],
            "description": "Automatic analysis unavailable",
            "confidence": 0.3,
            "provider": f"{self.provider}_fallback",
            "analyzed_frames": 0,
        }

    def get_category_id(self, content_type: str) -> int:
        """Obtenir l'ID de catégorie YouTube pour un type de contenu"""
        return self.CATEGORY_MAPPING.get(
            content_type.lower(), 24
        )  # 24 = Entertainment par défaut

    def analyze_video(self, video_path: Path, num_frames: int = 3) -> Dict:
        """
        Analyser complètement une vidéo

        Args:
            video_path: Chemin vers la vidéo
            num_frames: Nombre de frames à analyser

        Returns:
            Dictionnaire avec l'analyse complète
        """
        log.info(f"Début analyse vision de {video_path.name}")

        # Extraire les frames
        frame_paths = self.extract_frames(video_path, num_frames)

        try:
            # Analyser le contenu
            analysis = self.analyze_frames(frame_paths)

            # Ajouter l'ID de catégorie YouTube
            content_type = analysis.get("content_type", "entertainment")
            analysis["category_id"] = self.get_category_id(content_type)
            analysis["analysis_timestamp"] = datetime.now().isoformat()

            log.info(
                f"Analyse terminée: {content_type} (catégorie {analysis['category_id']})"
            )
            return analysis

        finally:
            # Nettoyer les frames temporaires
            for frame_path in frame_paths:
                try:
                    frame_path.unlink()
                except:
                    pass

            # Nettoyer le répertoire temporaire
            try:
                frame_paths[0].parent.rmdir()
            except:
                pass


def create_vision_analyzer(config: Dict) -> Optional[VisionAnalyzer]:
    """
    Créer un analyseur vision basé sur la configuration

    Args:
        config: Configuration vision depuis video.yaml

    Returns:
        Instance de VisionAnalyzer ou None si désactivé
    """
    if not config.get("enabled", False):
        return None

    provider = config.get("provider", "openai")
    provider_config = config.get(provider, {})

    try:
        return VisionAnalyzer(provider=provider, config=provider_config)
    except Exception as e:
        log.error(f"Impossible de créer l'analyseur vision {provider}: {e}")
        return None
