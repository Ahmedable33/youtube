from __future__ import annotations

import json
import os
import re
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
        raise RuntimeError(
            "OPENAI_API_KEY n'est pas défini dans les variables d'environnement"
        )
    if OpenAI is None:
        raise RuntimeError("Le paquet openai>=1.0 est requis")
    return OpenAI()


def generate_metadata(
    req: MetaRequest,
    config_path: str = "config/video.yaml",
    video_path: Optional[str] = None,
) -> dict:
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
    # Utiliser la configuration SEO comme valeurs par défaut (provider/model/host)
    seo_cfg = (config or {}).get("seo", {}) if isinstance(config, dict) else {}
    # Fallback: si load_config a échoué, tenter de lire le YAML brut pour récupérer le bloc SEO
    if not seo_cfg:
        try:
            from pathlib import Path

            cfg_path = Path(config_path)
            if cfg_path.exists() and cfg_path.suffix.lower() in {".yaml", ".yml"}:
                raw_doc = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
                if isinstance(raw_doc, dict):
                    seo_cfg = raw_doc.get("seo") or {}
        except Exception:
            seo_cfg = {}
    default_provider = (
        seo_cfg.get("provider") or os.environ.get("SEO_PROVIDER") or "openai"
    )
    provider = (req.provider or default_provider).lower()
    # Compléter req avec les valeurs config si provider=ollama
    if provider == "ollama":
        # Toujours préférer la config SEO côté modèle/hôte pour éviter un modèle OpenAI par défaut
        cfg_model = seo_cfg.get("model")
        cfg_host = seo_cfg.get("host")
        if cfg_model:
            req.model = cfg_model
        if cfg_host:
            req.host = cfg_host
        # Paramètres d'exécution Ollama optionnels (contrôle latence)
        seo_num_predict = None
        seo_timeout = None
        try:
            seo_num_predict = (
                int(os.environ.get("OLLAMA_NUM_PREDICT"))
                if os.environ.get("OLLAMA_NUM_PREDICT")
                else None
            )
        except Exception:
            seo_num_predict = None
        try:
            seo_timeout = (
                int(os.environ.get("OLLAMA_TIMEOUT"))
                if os.environ.get("OLLAMA_TIMEOUT")
                else None
            )
        except Exception:
            seo_timeout = None
        # Lire depuis YAML si présent
        if isinstance(seo_cfg, dict):
            if seo_cfg.get("num_predict") is not None and isinstance(
                seo_cfg.get("num_predict"), int
            ):
                seo_num_predict = seo_cfg.get("num_predict")
            if seo_cfg.get("timeout_seconds") is not None and isinstance(
                seo_cfg.get("timeout_seconds"), (int, float)
            ):
                seo_timeout = int(seo_cfg.get("timeout_seconds"))
        # Valeurs par défaut raisonnables
        if seo_num_predict is None:
            seo_num_predict = 200
        if seo_timeout is None:
            seo_timeout = 300
    else:
        seo_num_predict = None
        seo_timeout = None
    fast_mode = False
    if provider == "ollama":
        try:
            if isinstance(seo_cfg, dict):
                fast_mode = bool(seo_cfg.get("fast_mode", False))
        except Exception:
            fast_mode = False
    if provider == "none":
        metadata = _heuristic_generate(req, vision_analysis)
    elif provider == "ollama":
        try:
            metadata = (
                _ollama_generate_fast(req, vision_analysis)
                if fast_mode
                else _ollama_generate(req, vision_analysis)
            )
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
                            category_id=metadata.get("category_id"),
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
                if (
                    keyword.lower() not in title.lower()
                    and len(title) + len(keyword) + 3 < 60
                ):
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

    # Appliquer automatiquement les améliorations de description (mots-clés + CTA)
    try:
        desc = metadata.get("description", "") or ""

        # 1) Intégrer des mots-clés tendance proposés pour la description
        trending_from_desc: List[str] = []
        for s in suggestions:
            if (
                getattr(s, "confidence", 0) >= 0.7
                and getattr(s, "type", "") == "description"
            ):
                kws = getattr(s, "trending_keywords", []) or []
                for kw in kws:
                    if kw and kw not in trending_from_desc:
                        trending_from_desc.append(kw)

        if trending_from_desc:
            # Ne pas dupliquer des mots déjà présents
            desc_lower = desc.lower()
            to_add = [
                kw for kw in trending_from_desc if kw.lower() not in desc_lower
            ][:5]
            if to_add:
                # Ajouter en fin de description pour rester naturel
                if "Mots-clés:" not in desc:
                    desc += ("\n\n" if desc else "") + "Mots-clés: " + ", ".join(to_add)
                else:
                    # Fusion simple: ajouter seulement ceux absents
                    existing_line_idx = desc.find("Mots-clés:")
                    if existing_line_idx != -1:
                        existing_segment = desc[
                            existing_line_idx : existing_line_idx + 200
                        ]  # noqa: E203
                        for kw in to_add:
                            if kw.lower() not in existing_segment.lower():
                                desc += ", " + kw
        # 2) Ajouter un CTA s'il n'est pas déjà présent
        cta_patterns = [
            r"abonnez?[-\s]vous",
            r"\blike\b",
            r"partag",
            r"commentaire",
            r"cloche",
            r"subscribe",
            r"\bbell\b",
            r"share",
            r"comment",
        ]
        has_cta = any(re.search(p, desc, flags=re.IGNORECASE) for p in cta_patterns)
        if not has_cta:
            desc += (
                "\n\n" if desc else ""
            ) + "Abonnez-vous, likez et partagez pour soutenir la chaîne !"

        metadata["description"] = desc
    except Exception:
        # Ne bloque pas si une suggestion inattendue provoque une erreur
        pass

    return metadata


def _openai_generate(
    req: MetaRequest, client, vision_analysis: Optional[Dict] = None
) -> dict:
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
        model = req.model or os.environ.get("OLLAMA_MODEL", "llama3.1:8b")

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
        category_field = (
            '"category_id": numéro_catégorie,' if req.include_category else ""
        )

        system_prompt = f"""Tu es un expert YouTube SEO francophone.
Génère des métadonnées optimisées pour maximiser CTR et watch time.

{category_info if req.include_category else ""}

Règles:
- Titre: accrocheur, SEO-optimisé, max {req.max_title_chars} caractères
- Description: 2-3 paragraphes, mots-clés naturels, appel à l'action
- Tags: {req.max_tags} tags maximum, pertinents et populaires
{"- Catégorie: choisis la catégorie YouTube la plus appropriée selon le contenu" if req.include_category else ""}
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

            user_prompt_parts.append("\nAnalyse automatique du contenu vidéo:")
            user_prompt_parts.append(f"- Type de contenu détecté: {content_type}")
            user_prompt_parts.append(f"- Éléments visuels: {', '.join(tags[:5])}")
            user_prompt_parts.append(f"- Description visuelle: {description}")
            user_prompt_parts.append(f"- Confiance: {confidence:.1%}")
            user_prompt_parts.append(
                "Utilise ces informations pour optimiser le titre, la description et les tags."
            )

        if req.target_keywords:
            user_prompt_parts.append(
                f"Mots-clés cibles: {', '.join(req.target_keywords)}"
            )

        user_prompt = "\n\n".join(user_prompt_parts)

        # Construire un prompt unique (generate) pour limiter la latence et forcer le JSON
        composite_prompt = (
            f"{system_prompt}\n\n{user_prompt}\n\n"
            "Réponds STRICTEMENT avec un JSON valide correspondant au schéma demandé,"
            " sans texte additionnel."
        )

        # Paramètres via variables d'environnement (valeurs par défaut raisonnables)
        try:
            env_num_predict = int(os.environ.get("OLLAMA_NUM_PREDICT", "200"))
        except Exception:
            env_num_predict = 200
        try:
            env_timeout = int(os.environ.get("OLLAMA_TIMEOUT", "300"))
        except Exception:
            env_timeout = 300

        payload = {
            "model": model,
            "prompt": composite_prompt,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0.7,
                "top_p": 0.9,
                "num_predict": env_num_predict,
            },
        }

        # Timeout de lecture étendu pour laisser le temps au modèle de répondre sur CPU
        import httpx as _httpx

        client_timeout = _httpx.Timeout(env_timeout)
        with httpx.Client(timeout=client_timeout) as client:
            response = client.post(f"{host}/api/generate", json=payload)
            response.raise_for_status()

            result = response.json()
            content = result.get("response", "")

            # Parser le JSON de réponse (tolérant aux balises/code fences)
            data = _safe_json_loads(content)
            if data:
                # Ajouter category_id si détecté par vision
                if vision_analysis and not data.get("category_id"):
                    data["category_id"] = vision_analysis.get("category_id", 24)
                return data
            # Fallback heuristique si réponse non JSON
            return _heuristic_generate(req, vision_analysis)

    except Exception as e:
        import logging

        log = logging.getLogger(__name__)
        log.warning(f"Erreur Ollama: {e}")
        return _heuristic_generate(req, vision_analysis)


def _ollama_generate_fast(
    req: MetaRequest, vision_analysis: Optional[Dict] = None
) -> dict:
    """Version rapide: 3 appels courts à /api/generate pour limiter la latence CPU.

    - Titre seul (réponse brute)
    - Description courte (2 petits paragraphes)
    - Tags en JSON (tableau)
    """
    import httpx

    host = req.host or os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
    model = req.model or os.environ.get("OLLAMA_MODEL", "llama3.2:3b")

    # Paramètres env par défaut
    def _env_int(name: str, default: int) -> int:
        try:
            return int(os.environ.get(name, str(default)))
        except Exception:
            return default

    timeout_s = _env_int("OLLAMA_TIMEOUT", 180)
    title_predict = min(_env_int("OLLAMA_NUM_PREDICT", 80), 120)
    desc_predict = min(_env_int("OLLAMA_NUM_PREDICT", 160), 240)
    tags_predict = min(_env_int("OLLAMA_NUM_PREDICT", 80), 160)

    def _gen(prompt: str, num_predict: int, expect_json: bool = False) -> str:
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            **({"format": "json"} if expect_json else {}),
            "options": {"temperature": 0.6, "top_p": 0.9, "num_predict": num_predict},
        }
        import httpx as _httpx

        with httpx.Client(timeout=_httpx.Timeout(timeout_s)) as client:
            r = client.post(f"{host}/api/generate", json=payload)
            r.raise_for_status()
            return r.json().get("response", "").strip()

    # 1) Titre
    title_prompt = (
        f"Sujet: {req.topic}\n"
        f"Langue: {req.language}\n"
        f"Donne UNIQUEMENT un titre accrocheur (<= {req.max_title_chars} caractères)."
    )
    title_out = _gen(title_prompt, title_predict, expect_json=False)
    title = (
        title_out.splitlines()[0] if title_out else (req.topic or "Nouvelle vidéo")
    )[: req.max_title_chars]

    # 2) Description courte
    input_hint = (req.input_text or "").strip()
    desc_prompt = (
        f"Sujet: {req.topic}\nLangue: {req.language}\n"
        f"Ecris une description en 2 courts paragraphes (120-160 mots au total)."
        f" Evite les balises. Contenu seulement.\n"
        + (f"Contexte: {input_hint}\n" if input_hint else "")
    )
    description = _gen(desc_prompt, desc_predict, expect_json=False)

    # 3) Tags JSON
    tags_prompt = (
        f"Sujet: {req.topic}\nLangue: {req.language}\n"
        f"Retourne UNIQUEMENT un tableau JSON de {req.max_tags} tags en minuscules, sans #."
    )
    tags_raw = _gen(tags_prompt, tags_predict, expect_json=True)
    tags_data = _safe_json_loads(tags_raw)
    tags = []
    if isinstance(tags_data, list):
        tags = [str(t).strip().lstrip("#").lower() for t in tags_data if str(t).strip()]
    elif isinstance(tags_data, dict) and tags_data.get("tags"):
        tags = [
            str(t).strip().lstrip("#").lower()
            for t in tags_data.get("tags", [])
            if str(t).strip()
        ]
    tags = tags[: req.max_tags]

    # Catégorie heuristique (rapide) si demandé
    result = {
        "title": title
        or (req.topic[: req.max_title_chars] if req.topic else "Nouvelle vidéo"),
        "description": description or "",
        "tags": tags or ([req.topic.lower()] if req.topic else []),
    }
    if req.include_category:
        # heuristique légère identique au fallback
        result.update(_heuristic_generate(req, vision_analysis))
        # Remplacer par nos champs calculés
        result["title"] = title or result.get("title", "Nouvelle vidéo")
        result["description"] = description or result.get("description", "")
        result["tags"] = tags or result.get("tags", [])
    return result


def _heuristic_generate(
    req: MetaRequest, vision_analysis: Optional[Dict] = None
) -> dict:
    # Titre
    base = (req.input_text or req.topic or "").strip()
    title = (
        base.splitlines()[0][: req.max_title_chars]
        if base
        else (req.topic[: req.max_title_chars] if req.topic else "")
    )
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
            title = f"{title} - {content_type.title()}"[: req.max_title_chars]

        # Enrichir la description avec l'analyse visuelle
        if vision_desc:
            desc_lines.insert(-1, f"\nContenu détecté: {vision_desc}")

    # Catégorie heuristique basée sur mots-clés
    category_id = 22  # Défaut: People & Blogs
    if req.include_category:
        content = (req.input_text or req.topic or "").lower()
        if any(
            word in content
            for word in ["jeu", "gaming", "game", "stream", "joueur", "gamer"]
        ):
            category_id = 20  # Gaming
        elif any(
            word in content
            for word in [
                "tutoriel",
                "cours",
                "apprendre",
                "formation",
                "éducation",
                "tutorial",
                "learn",
            ]
        ):
            category_id = 27  # Education
        elif any(
            word in content
            for word in ["musique", "music", "chanson", "concert", "album"]
        ):
            category_id = 10  # Music
        elif any(
            word in content
            for word in [
                "tech",
                "technologie",
                "science",
                "informatique",
                "programming",
                "code",
            ]
        ):
            category_id = 28  # Science & Technology
        elif any(
            word in content
            for word in ["sport", "fitness", "football", "basketball", "workout"]
        ):
            category_id = 17  # Sports
        elif any(
            word in content
            for word in ["humour", "comedy", "funny", "blague", "sketch"]
        ):
            category_id = 23  # Comedy
        elif any(
            word in content
            for word in ["diy", "bricolage", "recette", "cuisine", "howto", "guide"]
        ):
            category_id = 26  # Howto & Style

        # Utiliser la catégorie détectée par vision si disponible et plus précise
        if vision_analysis and vision_analysis.get("category_id"):
            vision_category = vision_analysis.get("category_id")
            confidence = vision_analysis.get("confidence", 0)
            if confidence > 0.7:  # Haute confiance
                category_id = vision_category
        elif any(
            word in content for word in ["actualité", "news", "politique", "journal"]
        ):
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
    tags = list(set(tags))[: req.max_tags]

    result = {
        "title": title or "Nouvelle vidéo",
        "description": "\n".join(desc_lines),
        "tags": tags,
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
        t = t[start : end + 1]  # noqa: E203
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
