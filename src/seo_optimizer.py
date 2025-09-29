"""
Optimiseur SEO avancé pour YouTube
Intègre les tendances YouTube, analyse de concurrence et suggestions SEO
"""

import logging
import json
import re
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional
import aiohttp
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class TrendingKeyword:
    """Mot-clé tendance avec métadonnées"""

    keyword: str
    search_volume: int
    competition: str  # low, medium, high
    category: str
    region: str = "FR"
    timestamp: datetime = None


@dataclass
class CompetitorVideo:
    """Vidéo concurrente analysée"""

    title: str
    views: int
    likes: int
    published_date: datetime
    channel_name: str
    video_id: str
    tags: List[str]
    description_snippet: str


@dataclass
class SEOSuggestion:
    """Suggestion d'optimisation SEO"""

    type: str  # title, description, tags, thumbnail
    suggestion: str
    reason: str
    confidence: float
    trending_keywords: List[str]


class YouTubeTrendsAPI:
    """Interface pour récupérer les tendances YouTube"""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://www.googleapis.com/youtube/v3"

    async def get_trending_videos(
        self, region: str = "FR", category_id: Optional[int] = None
    ) -> List[Dict]:
        """Récupérer les vidéos en tendance"""
        try:
            params = {
                "part": "snippet,statistics",
                "chart": "mostPopular",
                "regionCode": region,
                "maxResults": 50,
                "key": self.api_key,
            }

            if category_id:
                params["videoCategoryId"] = category_id

            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/videos", params=params
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get("items", [])
                    else:
                        log.error(f"Erreur API YouTube Trends: {response.status}")
                        return []
        except Exception as e:
            log.error(f"Erreur récupération tendances: {e}")
            return []

    async def search_videos(self, query: str, max_results: int = 20) -> List[Dict]:
        """Rechercher des vidéos par mot-clé"""
        try:
            params = {
                "part": "snippet",
                "q": query,
                "type": "video",
                "maxResults": max_results,
                "order": "relevance",
                "key": self.api_key,
            }

            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/search", params=params
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get("items", [])
                    else:
                        log.error(f"Erreur recherche YouTube: {response.status}")
                        return []
        except Exception as e:
            log.error(f"Erreur recherche vidéos: {e}")
            return []


class CompetitorAnalyzer:
    """Analyseur de concurrence YouTube"""

    def __init__(self, youtube_api: YouTubeTrendsAPI):
        self.youtube_api = youtube_api

    async def analyze_competitors(
        self, topic: str, category_id: Optional[int] = None
    ) -> List[CompetitorVideo]:
        """Analyser les vidéos concurrentes pour un sujet"""
        competitors = []

        # Rechercher des vidéos similaires
        search_results = await self.youtube_api.search_videos(topic, max_results=20)

        for item in search_results:
            try:
                snippet = item.get("snippet", {})

                competitor = CompetitorVideo(
                    title=snippet.get("title", ""),
                    views=0,  # Nécessite une requête supplémentaire pour les stats
                    likes=0,
                    published_date=datetime.fromisoformat(
                        snippet.get("publishedAt", "").replace("Z", "+00:00")
                    ),
                    channel_name=snippet.get("channelTitle", ""),
                    video_id=item.get("id", {}).get("videoId", ""),
                    tags=[],  # Nécessite une requête supplémentaire
                    description_snippet=snippet.get("description", "")[:200],
                )

                competitors.append(competitor)

            except Exception as e:
                log.warning(f"Erreur analyse concurrent: {e}")
                continue

        return competitors

    def extract_trending_keywords(
        self, competitors: List[CompetitorVideo]
    ) -> List[TrendingKeyword]:
        """Extraire les mots-clés tendance des concurrents"""
        keyword_counts = {}

        for competitor in competitors:
            # Analyser les titres
            title_words = self._extract_keywords(competitor.title)
            for word in title_words:
                keyword_counts[word] = keyword_counts.get(word, 0) + competitor.views

        # Convertir en objets TrendingKeyword
        trending = []
        for keyword, score in sorted(
            keyword_counts.items(), key=lambda x: x[1], reverse=True
        )[:20]:
            trending.append(
                TrendingKeyword(
                    keyword=keyword,
                    search_volume=score,
                    competition="medium",  # Estimation
                    category="general",
                    timestamp=datetime.now(),
                )
            )

        return trending

    def _extract_keywords(self, text: str) -> List[str]:
        """Extraire les mots-clés d'un texte"""
        # Nettoyer et normaliser
        text = text.lower()
        text = re.sub(r"[^\w\s]", " ", text)

        # Mots vides français
        stop_words = {
            "le",
            "la",
            "les",
            "un",
            "une",
            "des",
            "du",
            "de",
            "et",
            "ou",
            "mais",
            "donc",
            "car",
            "ni",
            "or",
            "ce",
            "se",
            "que",
            "qui",
            "quoi",
            "dont",
            "où",
            "il",
            "elle",
            "on",
            "nous",
            "vous",
            "ils",
            "elles",
            "je",
            "tu",
            "me",
            "te",
            "se",
            "nous",
            "vous",
            "mon",
            "ma",
            "mes",
            "ton",
            "ta",
            "tes",
            "son",
            "sa",
            "ses",
            "notre",
            "votre",
            "leur",
            "leurs",
            "ce",
            "cet",
            "cette",
            "ces",
            "à",
            "au",
            "aux",
            "avec",
            "sans",
            "pour",
            "par",
            "sur",
            "sous",
            "dans",
            "en",
            "vers",
            "chez",
            "depuis",
            "pendant",
            "avant",
            "après",
            "très",
            "plus",
            "moins",
            "aussi",
            "bien",
            "mal",
            "beaucoup",
            "peu",
            "trop",
            "assez",
            "comment",
            "pourquoi",
            "quand",
            "how",
            "what",
            "when",
            "where",
            "why",
            "the",
            "a",
            "an",
            "and",
            "or",
            "but",
            "in",
            "on",
            "at",
            "to",
            "for",
            "of",
            "with",
            "by",
            "from",
            "up",
            "about",
            "into",
            "through",
            "during",
            "before",
            "after",
            "above",
            "below",
            "between",
            "among",
            "this",
            "that",
            "these",
            "those",
        }

        words = text.split()
        keywords = [
            w for w in words if len(w) > 3 and w not in stop_words and w.isalpha()
        ]

        return keywords


class SEOOptimizer:
    """Optimiseur SEO principal"""

    def __init__(self, youtube_api_key: str, config: Optional[Dict] = None):
        self.youtube_api = YouTubeTrendsAPI(youtube_api_key)
        self.competitor_analyzer = CompetitorAnalyzer(self.youtube_api)
        self.config = config or {}

    async def generate_seo_suggestions(
        self,
        title: str,
        description: str,
        tags: List[str],
        category_id: Optional[int] = None,
    ) -> List[SEOSuggestion]:
        """Générer des suggestions SEO basées sur les tendances et la concurrence"""
        suggestions = []

        # Analyser la concurrence
        competitors = await self.competitor_analyzer.analyze_competitors(
            title, category_id
        )
        trending_keywords = self.competitor_analyzer.extract_trending_keywords(
            competitors
        )

        # Suggestions pour le titre
        title_suggestions = self._analyze_title(title, trending_keywords, competitors)
        suggestions.extend(title_suggestions)

        # Suggestions pour la description
        desc_suggestions = self._analyze_description(description, trending_keywords)
        suggestions.extend(desc_suggestions)

        # Suggestions pour les tags
        tag_suggestions = self._analyze_tags(tags, trending_keywords)
        suggestions.extend(tag_suggestions)

        return suggestions

    def _analyze_title(
        self,
        title: str,
        trending_keywords: List[TrendingKeyword],
        competitors: List[CompetitorVideo],
    ) -> List[SEOSuggestion]:
        """Analyser et suggérer des améliorations pour le titre"""
        suggestions = []

        # Vérifier la longueur
        if len(title) > 60:
            suggestions.append(
                SEOSuggestion(
                    type="title",
                    suggestion=f"Raccourcir le titre (actuellement {len(title)} caractères, recommandé: 50-60)",
                    reason="Les titres courts sont mieux affichés dans les résultats",
                    confidence=0.8,
                    trending_keywords=[],
                )
            )

        # Suggérer des mots-clés tendance manquants
        title_lower = title.lower()
        missing_keywords = []

        for keyword in trending_keywords[:5]:  # Top 5 keywords
            if keyword.keyword not in title_lower and len(keyword.keyword) > 3:
                missing_keywords.append(keyword.keyword)

        if missing_keywords:
            suggestions.append(
                SEOSuggestion(
                    type="title",
                    suggestion=f"Ajouter des mots-clés tendance: {', '.join(missing_keywords[:3])}",
                    reason="Ces mots-clés sont populaires dans votre niche",
                    confidence=0.7,
                    trending_keywords=missing_keywords[:3],
                )
            )

        # Analyser les titres concurrents performants
        if competitors:
            avg_title_length = sum(len(c.title) for c in competitors) / len(competitors)
            if abs(len(title) - avg_title_length) > 15:
                suggestions.append(
                    SEOSuggestion(
                        type="title",
                        suggestion=f"Ajuster la longueur du titre (moyenne concurrents: {avg_title_length:.0f} caractères)",
                        reason="S'aligner sur les pratiques des concurrents performants",
                        confidence=0.6,
                        trending_keywords=[],
                    )
                )

        return suggestions

    def _analyze_description(
        self, description: str, trending_keywords: List[TrendingKeyword]
    ) -> List[SEOSuggestion]:
        """Analyser et suggérer des améliorations pour la description"""
        suggestions = []

        # Vérifier la longueur
        if len(description) < 125:
            suggestions.append(
                SEOSuggestion(
                    type="description",
                    suggestion="Étoffer la description (minimum 125 caractères recommandé)",
                    reason="Les descriptions détaillées améliorent le référencement",
                    confidence=0.8,
                    trending_keywords=[],
                )
            )

        # Vérifier la présence de mots-clés tendance
        desc_lower = description.lower()
        missing_keywords = []

        for keyword in trending_keywords[:10]:
            if keyword.keyword not in desc_lower:
                missing_keywords.append(keyword.keyword)

        if missing_keywords:
            suggestions.append(
                SEOSuggestion(
                    type="description",
                    suggestion=f"Intégrer naturellement ces mots-clés: {', '.join(missing_keywords[:5])}",
                    reason="Améliorer la découvrabilité avec des termes populaires",
                    confidence=0.7,
                    trending_keywords=missing_keywords[:5],
                )
            )

        # Vérifier l'appel à l'action
        cta_patterns = [
            r"abonnez?[-\s]vous",
            r"like",
            r"partag",
            r"commentaire",
            r"cloche",
            r"subscribe",
            r"bell",
            r"share",
            r"comment",
        ]

        has_cta = any(re.search(pattern, desc_lower) for pattern in cta_patterns)

        if not has_cta:
            suggestions.append(
                SEOSuggestion(
                    type="description",
                    suggestion="Ajouter un appel à l'action (abonnement, like, partage)",
                    reason="Les CTA augmentent l'engagement et la rétention",
                    confidence=0.6,
                    trending_keywords=[],
                )
            )

        return suggestions

    def _analyze_tags(
        self, tags: List[str], trending_keywords: List[TrendingKeyword]
    ) -> List[SEOSuggestion]:
        """Analyser et suggérer des améliorations pour les tags"""
        suggestions = []

        # Vérifier le nombre de tags
        if len(tags) < 5:
            suggestions.append(
                SEOSuggestion(
                    type="tags",
                    suggestion=f"Ajouter plus de tags (actuellement {len(tags)}, recommandé: 8-12)",
                    reason="Plus de tags = plus d'opportunités de découverte",
                    confidence=0.8,
                    trending_keywords=[],
                )
            )
        elif len(tags) > 15:
            suggestions.append(
                SEOSuggestion(
                    type="tags",
                    suggestion=f"Réduire le nombre de tags (actuellement {len(tags)}, recommandé: 8-12)",
                    reason="Trop de tags peut diluer la pertinence",
                    confidence=0.7,
                    trending_keywords=[],
                )
            )

        # Suggérer des tags tendance
        tags_lower = [tag.lower() for tag in tags]
        suggested_tags = []

        for keyword in trending_keywords[:15]:
            if keyword.keyword not in tags_lower and len(keyword.keyword) > 2:
                suggested_tags.append(keyword.keyword)

        if suggested_tags:
            suggestions.append(
                SEOSuggestion(
                    type="tags",
                    suggestion=f"Ajouter ces tags tendance: {', '.join(suggested_tags[:5])}",
                    reason="Tags populaires dans votre catégorie",
                    confidence=0.7,
                    trending_keywords=suggested_tags[:5],
                )
            )

        return suggestions

    async def get_trending_keywords_for_category(
        self, category_id: int, region: str = "FR"
    ) -> List[TrendingKeyword]:
        """Récupérer les mots-clés tendance pour une catégorie"""
        trending_videos = await self.youtube_api.get_trending_videos(
            region, category_id
        )

        keyword_counts = {}

        for video in trending_videos:
            snippet = video.get("snippet", {})
            stats = video.get("statistics", {})

            title = snippet.get("title", "")
            views = int(stats.get("viewCount", 0))

            # Extraire mots-clés du titre
            keywords = self.competitor_analyzer._extract_keywords(title)

            for keyword in keywords:
                if keyword not in keyword_counts:
                    keyword_counts[keyword] = {"count": 0, "total_views": 0}

                keyword_counts[keyword]["count"] += 1
                keyword_counts[keyword]["total_views"] += views

        # Convertir en TrendingKeyword
        trending = []
        for keyword, data in keyword_counts.items():
            if data["count"] >= 2:  # Apparaît dans au moins 2 vidéos
                trending.append(
                    TrendingKeyword(
                        keyword=keyword,
                        search_volume=data["total_views"]
                        // data["count"],  # Moyenne des vues
                        competition="medium",
                        category=str(category_id),
                        region=region,
                        timestamp=datetime.now(),
                    )
                )

        # Trier par popularité
        trending.sort(key=lambda x: x.search_volume, reverse=True)

        return trending[:50]


class ABTestManager:
    """Gestionnaire de tests A/B pour titres et thumbnails"""

    def __init__(self, storage_path: Path):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(exist_ok=True)

    def create_ab_test(self, video_id: str, variants: Dict[str, Dict]) -> str:
        """Créer un test A/B avec plusieurs variants"""
        test_id = f"ab_{video_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        test_data = {
            "test_id": test_id,
            "video_id": video_id,
            "created_at": datetime.now().isoformat(),
            "status": "active",
            "variants": variants,
            "results": {},
        }

        # Sauvegarder le test
        test_file = self.storage_path / f"{test_id}.json"
        with open(test_file, "w", encoding="utf-8") as f:
            json.dump(test_data, f, ensure_ascii=False, indent=2)

        log.info(f"Test A/B créé: {test_id} avec {len(variants)} variants")
        return test_id

    def generate_title_variants(
        self, base_title: str, trending_keywords: List[str]
    ) -> Dict[str, Dict]:
        """Générer des variants de titre pour test A/B"""
        variants = {"original": {"title": base_title, "type": "control"}}

        # Variant avec emoji
        if not any(ord(char) > 127 for char in base_title):  # Pas d'emoji déjà
            variants["emoji"] = {"title": f"🔥 {base_title}", "type": "emoji"}

        # Variant avec mot-clé tendance
        if trending_keywords:
            keyword = trending_keywords[0]
            if keyword.lower() not in base_title.lower():
                variants["trending"] = {
                    "title": f"{base_title} - {keyword.title()}",
                    "type": "trending_keyword",
                }

        # Variant avec question
        if not base_title.endswith("?"):
            variants["question"] = {
                "title": f"{base_title} - Mais Comment ?",
                "type": "question",
            }

        # Variant avec urgence
        urgency_words = ["URGENT", "INCROYABLE", "RÉVÉLÉ", "SECRET"]
        if not any(word in base_title.upper() for word in urgency_words):
            variants["urgency"] = {
                "title": f"INCROYABLE: {base_title}",
                "type": "urgency",
            }

        return variants

    def get_active_tests(self) -> List[Dict]:
        """Récupérer tous les tests A/B actifs"""
        active_tests = []

        for test_file in self.storage_path.glob("ab_*.json"):
            try:
                with open(test_file, "r", encoding="utf-8") as f:
                    test_data = json.load(f)

                if test_data.get("status") == "active":
                    active_tests.append(test_data)
            except Exception as e:
                log.warning(f"Erreur lecture test A/B {test_file}: {e}")

        return active_tests

    def update_test_results(self, test_id: str, variant_id: str, metrics: Dict):
        """Mettre à jour les résultats d'un variant"""
        test_file = self.storage_path / f"{test_id}.json"

        if not test_file.exists():
            log.error(f"Test A/B introuvable: {test_id}")
            return

        try:
            with open(test_file, "r", encoding="utf-8") as f:
                test_data = json.load(f)

            if "results" not in test_data:
                test_data["results"] = {}

            test_data["results"][variant_id] = {
                **metrics,
                "updated_at": datetime.now().isoformat(),
            }

            with open(test_file, "w", encoding="utf-8") as f:
                json.dump(test_data, f, ensure_ascii=False, indent=2)

            log.info(f"Résultats mis à jour pour {test_id}/{variant_id}")

        except Exception as e:
            log.error(f"Erreur mise à jour test A/B: {e}")


def create_seo_optimizer(config: Dict) -> Optional[SEOOptimizer]:
    """Créer un optimiseur SEO basé sur la configuration"""
    if not config.get("enabled", False):
        return None

    youtube_api_key = config.get("youtube_api_key")
    if not youtube_api_key:
        log.warning("Clé API YouTube manquante pour l'optimiseur SEO")
        return None

    try:
        return SEOOptimizer(youtube_api_key, config)
    except Exception as e:
        log.error(f"Impossible de créer l'optimiseur SEO: {e}")
        return None
