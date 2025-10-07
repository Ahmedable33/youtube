import types

from src.ai_generator import _apply_seo_suggestions


def _mk_suggestion(type_: str, suggestion: str, confidence: float, trending):
    return types.SimpleNamespace(
        type=type_,
        suggestion=suggestion,
        confidence=confidence,
        trending_keywords=trending,
    )


def test_apply_seo_suggestions_adds_keywords_and_cta():
    metadata = {
        "title": "Titre de base",
        "description": "",
        "tags": ["base"],
    }

    suggestions = [
        # Description: propose des mots-clés tendance
        _mk_suggestion(
            "description",
            "Intégrer naturellement ces mots-clés: kw1, kw2",
            0.9,
            ["kw1", "kw2"],
        ),
    ]

    out = _apply_seo_suggestions(metadata, suggestions)

    desc = out.get("description", "")
    assert "Mots-clés:" in desc
    assert "kw1" in desc and "kw2" in desc
    # CTA ajouté s'il est absent
    assert "Abonnez-vous" in desc


def test_apply_seo_suggestions_title_and_tags_merging():
    metadata = {
        "title": "Tutoriel Python",
        "description": "Intro au sujet.",
        "tags": ["python"],
    }

    suggestions = [
        # Titre: l'implémentation applique seulement si le texte contient cette sous-chaîne
        _mk_suggestion(
            "title",
            "Ajouter des mots-clés tendance: optimisation, performance, astuces",
            0.85,
            ["optimisation", "performance", "astuces"],
        ),
        # Tags: propose 3 tags, on en a déjà 1
        _mk_suggestion(
            "tags",
            "Ajouter ces tags tendance: optimisation, performance, astuces",
            0.9,
            ["optimisation", "performance", "astuces"],
        ),
    ]

    out = _apply_seo_suggestions(metadata, suggestions)

    # Titre enrichi (limité à 2 mots-clés dans l'implémentation)
    assert "optimisation" in out["title"]
    assert "performance" in out["title"]

    # Tags enrichis (<= 12, et non dupliqués)
    tags = out.get("tags", [])
    assert "optimisation" in tags and "performance" in tags and "astuces" in tags
