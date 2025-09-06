from __future__ import annotations

import json
import os
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
    target_keywords: Optional[List[str]] = None
    channel_style: Optional[str] = None
    include_hashtags: bool = True
    max_tags: int = 15
    max_title_chars: int = 70
    # Provider/model
    provider: Optional[str] = None  # 'openai' | 'ollama' | 'none'
    model: Optional[str] = None  # e.g. 'gpt-4o-mini' or 'llama3.1:8b-instruct'
    host: Optional[str] = None   # e.g. OLLAMA_HOST
    input_text: Optional[str] = None  # Script/transcript/context facultatif


def _get_openai_client():
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY n'est pas défini dans les variables d'environnement")
    if OpenAI is None:
        raise RuntimeError("Le paquet openai>=1.0 est requis")
    return OpenAI()


def generate_metadata(req: MetaRequest) -> Dict[str, Any]:
    provider = (req.provider or os.environ.get("SEO_PROVIDER") or "openai").lower()
    if provider == "none":
        return _heuristic_generate(req)

    if provider == "ollama":
        try:
            return _ollama_generate(req)
        except Exception:
            # fallback heuristique si Ollama indisponible
            return _heuristic_generate(req)

    # défaut: openai si possible, sinon heuristique
    try:
        client = _get_openai_client()
    except Exception:
        return _heuristic_generate(req)

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


def _ollama_generate(req: MetaRequest) -> Dict[str, Any]:
    import httpx

    host = req.host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    model = req.model or os.environ.get("OLLAMA_MODEL", "llama3.1:8b-instruct")

    sys_prompt = (
        "Tu es un expert YouTube SEO francophone.\n"
        "Objectif: générer un titre, une description et des tags optimisés.\n"
        "Contraintes: Titre <= {max_title} caractères. Description 150-300 mots. Tags (sans #) jusqu'à {max_tags}.\n"
        "Retourne STRICTEMENT un JSON valide sans texte hors JSON: {{\"title\":str,\"description\":str,\"tags\":[str],\"hashtags\":[str],\"seo_tips\":[str]}}"
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
    }

    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": "PARAMS = \n" + json.dumps(user_payload, ensure_ascii=False)},
    ]

    payload = {"model": model, "messages": messages, "stream": False}
    with httpx.Client(timeout=60) as client:
        r = client.post(f"{host}/api/chat", json=payload)
        r.raise_for_status()
        data = r.json()
        content = data.get("message", {}).get("content", "{}")
        parsed = _safe_json_loads(content)
        return {
            "title": parsed.get("title", ""),
            "description": parsed.get("description", ""),
            "tags": parsed.get("tags", [])[: req.max_tags],
            "hashtags": parsed.get("hashtags", []),
            "seo_tips": parsed.get("seo_tips", []),
        }


def _heuristic_generate(req: MetaRequest) -> Dict[str, Any]:
    # Titre
    base = (req.input_text or req.topic or "").strip()
    title = base.splitlines()[0][: req.max_title_chars] if base else (req.topic[: req.max_title_chars] if req.topic else "")
    # Description
    desc_lines = []
    if req.input_text:
        desc_lines.append(req.input_text.strip())
    desc_lines.append("\n--\nAbonnez-vous pour plus de contenus !")
    description = "\n".join(desc_lines).strip()
    # Tags simples: extraire mots >3 chars uniques
    import re
    words = re.findall(r"[\wàâçéèêëîïôûùüÿñæœ-]{4,}", (req.input_text or req.topic or "").lower())
    uniq = []
    for w in words:
        if w not in uniq:
            uniq.append(w)
    tags = uniq[: req.max_tags]
    return {"title": title, "description": description, "tags": tags, "hashtags": [], "seo_tips": []}


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
