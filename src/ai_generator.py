from __future__ import annotations

import json
import os
from .config_loader import load_config
from .vision_analyzer import create_vision_analyzer
from .seo_optimizer import create_seo_optimizer
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

import yaml

try:
    # New OpenAI SDK (>=1.0)
    from openai import OpenAI  # type: ignore
except Exception:  # pragma: no cover - fallback if old SDK
    OpenAI = None  # type: ignore


@dataclass
class MetaRequest:
    topic: str
    language: str = "fr"
    tone: str = "informatif"
    target_keywords: Optional[list[str]] = None
    channel_style: Optional[str] = None
    include_hashtags: bool = True
    max_tags: int = 15
    max_title_chars: int = 70
    provider: Optional[str] = None
    model: Optional[str] = None
    host: Optional[str] = None
    input_text: Optional[str] = None
    include_category: bool = True


def _get_openai_client():
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY n'est pas défini dans les variables d'environnement")
    if OpenAI is None:
        raise RuntimeError("Le paquet openai>=1.0 est requis")
    return OpenAI()


def generate_metadata(req: MetaRequest, config_path: str = "config/video.yaml", video_path: Optional[str] = None) -> dict:
    # Charger la configuration
    config = None
    try:
        config = load_config(config_path)
    except Exception as e:
        import logging
        log = logging.getLogger(__name__)
        log.warning(f"Erreur chargement config: {e}")
    
    # Analyser le contenu vidéo avec IA Vision si disponible
    vision_analysis = None
    if video_path and config:
        try:
            from pathlib import Path
            vision_config = config.get("vision", {})
            
            if vision_config.get("enabled", False):
                analyzer = create_vision_analyzer(vision_config)
                if analyzer:
                    vision_analysis = analyzer.analyze_video(Path(video_path))
        except Exception as e:
            import logging
            log = logging.getLogger(__name__)
            log.warning(f"Erreur analyse vision: {e}")
    
    # Générer les métadonnées de base
    provider = (req.provider or os.environ.get("SEO_PROVIDER") or "openai").lower()
    if provider == "none":
        metadata = _heuristic_generate(req, vision_analysis)
    elif provider == "ollama":
        try:
            metadata = _ollama_generate(req, vision_analysis)
        except Exception:
            # fallback heuristique si Ollama indisponible
            metadata = _heuristic_generate(req, vision_analysis)
    else:
        # défaut: openai si possible, sinon heuristique
        try:
            client = _get_openai_client()
            metadata = _openai_generate(req, client, vision_analysis)
        except Exception:
            metadata = _heuristic_generate(req, vision_analysis)
    
    # Appliquer l'optimisation SEO avancée si activée
    if config and config.get("seo_advanced", {}).get("enabled", False):
        try:
            import asyncio
            seo_config = config.get("seo_advanced", {})
            optimizer = create_seo_optimizer(seo_config)
            
            if optimizer:
                # Exécuter l'optimisation SEO de manière asynchrone
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                try:
                    suggestions = loop.run_until_complete(
                        optimizer.generate_seo_suggestions(
                            title=metadata.get("title", ""),
                            description=metadata.get("description", ""),
                            tags=metadata.get("tags", []),
                            category_id=metadata.get("category_id")
                        )
                    )
                    
                    # Appliquer les suggestions avec haute confiance
                    metadata = _apply_seo_suggestions(metadata, suggestions)
                    
                finally:
                    loop.close()
                    
        except Exception as e:
            import logging
            log = logging.getLogger(__name__)
            log.warning(f"Erreur optimisation SEO avancée: {e}")
    
    return metadata


def _apply_seo_suggestions(metadata: dict, suggestions: List) -> dict:
    """Appliquer les suggestions SEO aux métadonnées"""
    for suggestion in suggestions:
        if suggestion.confidence < 0.7:  # Ignorer les suggestions peu fiables
            continue
            
        if suggestion.type == "title" and "mots-clés tendance" in suggestion.suggestion:
            # Ajouter des mots-clés tendance au titre si pas trop long
            title = metadata.get("title", "")
            keywords = suggestion.trending_keywords[:2]  # Max 2 mots-clés
            
            for keyword in keywords:
                if keyword.lower() not in title.lower() and len(title) + len(keyword) + 3 < 60:
                    title = f"{title} {keyword}"
            
            metadata["title"] = title
            
        elif suggestion.type == "tags":
            # Ajouter des tags tendance
            current_tags = metadata.get("tags", [])
            new_tags = suggestion.trending_keywords[:3]  # Max 3 nouveaux tags
            
            for tag in new_tags:
                if tag not in current_tags and len(current_tags) < 12:
                    current_tags.append(tag)
            
            metadata["tags"] = current_tags
    
    return metadata


def _openai_generate(req: MetaRequest, client, vision_analysis: Optional[Dict] = None) -> dict:
    sys_prompt = (
        "Tu es un expert YouTube SEO francophone.\n"
        "Objectif: générer un titre, une description et des tags optimisés pour maximiser CTR et watch time.\n"
        "Contraintes: \n"
        "- Titre: accrocheur, clair, <= {max_title} caractères.\n"
        "- Description: 150-300 mots, premières lignes riches en mots-clés, sections claires, CTA à s'abonner.\n"
        "- Tags: jusqu'à {max_tags} tags pertinents (sans #), mélange courte/longue traîne.\n"
        "- Hashtags: 3-5, en fin de description si include_hashtags=true.\n"
        "- Retourne STRICTEMENT un JSON valide sans texte hors JSON."
    ).format(max_title=req.max_title_chars, max_tags=req.max_tags)

    user_payload = {
        "topic": req.topic,
        "language": req.language,
        "tone": req.tone,
        "target_keywords": req.target_keywords or [],
        "channel_style": req.channel_style or "",
        "include_hashtags": req.include_hashtags,
        "max_tags": req.max_tags,
        "max_title_chars": req.max_title_chars,
        "input_text": req.input_text or "",
        "expected_schema": {
            "title": "string",
            "description": "string",
            "tags": ["string"],
            "hashtags": ["string"],
            "seo_tips": ["string"],
        },
    }

    messages = [
        {"role": "system", "content": sys_prompt},
        {
            "role": "user",
            "content": (
                "Génère des métadonnées YouTube optimisées selon ces paramètres, en {lang}.\n"
                "Retourne un JSON conforme à expected_schema.\n"
                "PARAMS = \n" + json.dumps(user_payload, ensure_ascii=False)
            ).format(lang=req.language),
        },
    ]

    resp = client.chat.completions.create(
        model=req.model or os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        messages=messages,
        temperature=0.7,
        max_tokens=800,
    )

    content = resp.choices[0].message.content if resp.choices else "{}"
    data = _safe_json_loads(content)

    # Normalisation minimale
    return {
        "title": data.get("title", ""),
        "description": data.get("description", ""),
        "tags": data.get("tags", [])[: req.max_tags],
        "hashtags": data.get("hashtags", []),
        "seo_tips": data.get("seo_tips", []),
    }


def _ollama_generate(req: MetaRequest, vision_analysis: Optional[Dict] = None) -> dict:
    """Génère métadonnées via Ollama local."""
    try:
        import httpx
        
        host = req.host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        model = req.model or os.environ.get("OLLAMA_MODEL", "llama3.1:8b-instruct")
        
        # Mapping des catégories YouTube
        category_info = """
Catégories YouTube disponibles:
- Gaming (20): Jeux vidéo, streams, gaming
- Education (27): Tutoriels, cours, formations
- Entertainment (24): Divertissement général
- Music (10): Musique, clips, concerts
- Tech (28): Technologie, sciences, informatique
- News (25): Actualités, politique
- Sports (17): Sport, fitness
- Comedy (23): Humour, sketchs
- Howto (26): DIY, guides pratiques
- People (22): Vlogs, lifestyle (défaut)
"""
        
        # Construire le prompt système
        category_field = '"category_id": numéro_catégorie,' if req.include_category else ""
        
        system_prompt = f"""Tu es un expert YouTube SEO francophone.
Génère des métadonnées optimisées pour maximiser CTR et watch time.

{category_info if req.include_category else ""}

Règles:
- Titre: accrocheur, SEO-optimisé, max {req.max_title_chars} caractères
- Description: 2-3 paragraphes, mots-clés naturels, appel à l'action
- Tags: {req.max_tags} tags maximum, pertinents et populaires
{f"- Catégorie: choisis la catégorie YouTube la plus appropriée selon le contenu" if req.include_category else ""}
- Ton: {req.tone}
- Langue: {req.language}

Réponds UNIQUEMENT en JSON valide avec cette structure exacte:
{{
  "title": "titre accrocheur (max {req.max_title_chars} caractères)",
  "description": "description détaillée avec mots-clés naturels",
  "tags": ["tag1", "tag2", "tag3"]{("," + category_field) if req.include_category else ""}
}}"""

        # Construire le prompt utilisateur avec les informations disponibles
        user_prompt_parts = [f"Sujet: {req.topic}"]
        
        if req.input_text:
            user_prompt_parts.append(f"Contexte fourni: {req.input_text}")
        
        # Ajouter les informations de l'analyse vision si disponible
        if vision_analysis:
            content_type = vision_analysis.get("content_type", "")
            tags = vision_analysis.get("tags", [])
            description = vision_analysis.get("description", "")
            confidence = vision_analysis.get("confidence", 0)
            
            user_prompt_parts.append(f"\nAnalyse automatique du contenu vidéo:")
            user_prompt_parts.append(f"- Type de contenu détecté: {content_type}")
            user_prompt_parts.append(f"- Éléments visuels: {', '.join(tags[:5])}")
            user_prompt_parts.append(f"- Description visuelle: {description}")
            user_prompt_parts.append(f"- Confiance: {confidence:.1%}")
            user_prompt_parts.append("Utilise ces informations pour optimiser le titre, la description et les tags.")
        
        if req.target_keywords:
            user_prompt_parts.append(f"Mots-clés cibles: {', '.join(req.target_keywords)}")
        
        user_prompt = "\n\n".join(user_prompt_parts)

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "stream": False,
            "options": {
                "temperature": 0.7,
                "top_p": 0.9
            }
        }

        with httpx.Client(timeout=30.0) as client:
            response = client.post(f"{host}/api/chat", json=payload)
            response.raise_for_status()
            
            result = response.json()
            content = result.get("message", {}).get("content", "")
            
            # Parser le JSON de réponse
            try:
                metadata = json.loads(content)
                
                # Ajouter category_id si détecté par vision
                if vision_analysis and not metadata.get("category_id"):
                    metadata["category_id"] = vision_analysis.get("category_id", 24)
                
                return metadata
            except json.JSONDecodeError:
                # Fallback heuristique
                return _heuristic_generate(req, vision_analysis)
    
    except Exception as e:
        import logging
        log = logging.getLogger(__name__)
        log.warning(f"Erreur Ollama: {e}")
        return _heuristic_generate(req, vision_analysis)


def _heuristic_generate(req: MetaRequest, vision_analysis: Optional[Dict] = None) -> dict:
    # Titre
    base = (req.input_text or req.topic or "").strip()
    title = base.splitlines()[0][: req.max_title_chars] if base else (req.topic[: req.max_title_chars] if req.topic else "")
    # Description
    desc_lines = []
    if req.input_text:
        desc_lines.append(req.input_text.strip())
    desc_lines.append("\n--\nAbonnez-vous pour plus de contenus !")
    
    # Intégrer les informations de l'analyse vision si disponible
    if vision_analysis:
        content_type = vision_analysis.get("content_type", "")
        vision_tags = vision_analysis.get("tags", [])
        vision_desc = vision_analysis.get("description", "")
        
        # Améliorer le titre avec le type de contenu détecté
        if content_type and content_type not in title.lower():
            title = f"{title} - {content_type.title()}"[:req.max_title_chars]
        
        # Enrichir la description avec l'analyse visuelle
        if vision_desc:
            desc_lines.insert(-1, f"\nContenu détecté: {vision_desc}")
    
    # Catégorie heuristique basée sur mots-clés
    category_id = 22  # Défaut: People & Blogs
    if req.include_category:
        content = (req.input_text or req.topic or "").lower()
        if any(word in content for word in ["jeu", "gaming", "game", "stream", "joueur", "gamer"]):
            category_id = 20  # Gaming
        elif any(word in content for word in ["tutoriel", "cours", "apprendre", "formation", "éducation", "tutorial", "learn"]):
            category_id = 27  # Education
        elif any(word in content for word in ["musique", "music", "chanson", "concert", "album"]):
            category_id = 10  # Music
        elif any(word in content for word in ["tech", "technologie", "science", "informatique", "programming", "code"]):
            category_id = 28  # Science & Technology
        elif any(word in content for word in ["sport", "fitness", "football", "basketball", "workout"]):
            category_id = 17  # Sports
        elif any(word in content for word in ["humour", "comedy", "funny", "blague", "sketch"]):
            category_id = 23  # Comedy
        elif any(word in content for word in ["diy", "bricolage", "recette", "cuisine", "howto", "guide"]):
            category_id = 26  # Howto & Style
        
        # Utiliser la catégorie détectée par vision si disponible et plus précise
        if vision_analysis and vision_analysis.get("category_id"):
            vision_category = vision_analysis.get("category_id")
            confidence = vision_analysis.get("confidence", 0)
            if confidence > 0.7:  # Haute confiance
                category_id = vision_category
        elif any(word in content for word in ["actualité", "news", "politique", "journal"]):
            category_id = 25  # News & Politics
    
    # Tags heuristiques
    tags = []
    if req.input_text:
        # Extraire mots-clés simples
        words = req.input_text.lower().split()
        keywords = [w.strip(".,!?;:") for w in words if len(w) > 3 and w.isalpha()]
        tags.extend(keywords[:5])
    
    # Ajouter tags de l'analyse vision
    if vision_analysis and vision_analysis.get("tags"):
        vision_tags = vision_analysis.get("tags", [])
        tags.extend(vision_tags[:5])
    
    # Ajouter le topic comme tag
    if req.topic:
        tags.append(req.topic.lower())
    
    # Nettoyer et limiter les tags
    tags = list(set(tags))[:req.max_tags]
    
    result = {
        "title": title or "Nouvelle vidéo",
        "description": "\n".join(desc_lines),
        "tags": tags
    }
    
    if req.include_category:
        result["category_id"] = category_id
    
    return result


def _safe_json_loads(text: str) -> Dict[str, Any]:
    """Tente de parser du JSON éventuellement entouré de balises de code."""
    t = text.strip()
    if t.startswith("```"):
        # Retire fences markdown
        t = t.strip("`")
        # Cherche la première accolade
    # Extrait la plus grande sous-chaîne JSON plausible
    start = t.find("{")
    end = t.rfind("}")
    if start != -1 and end != -1 and end > start:
        t = t[start : end + 1]
    try:
        return json.loads(t)
    except Exception:
        return {}


def write_metadata_to_config(
    out_config_path: str,
    *,
    video_path: Optional[str] = None,
    title: str,
    description: str,
    tags: Iterable[str],
    category_id: int | str = 22,
    privacy_status: str = "private",
) -> None:
    """Écrit/merge des métadonnées générées dans un fichier YAML."""
    doc = {}
    if os.path.exists(out_config_path):
        try:
            with open(out_config_path, "r", encoding="utf-8") as f:
                doc = yaml.safe_load(f) or {}
        except Exception:
            doc = {}
    if video_path:
        doc["video_path"] = video_path
    doc["title"] = title
    doc["description"] = description
    doc["tags"] = list(tags)
    doc.setdefault("category_id", category_id)
    doc.setdefault("privacy_status", privacy_status)

    with open(out_config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(doc, f, allow_unicode=True, sort_keys=False)
