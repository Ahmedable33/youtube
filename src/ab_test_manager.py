"""
Gestionnaire de tests A/B pour optimisation YouTube
Permet de tester différents titres, descriptions et thumbnails
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
import hashlib

log = logging.getLogger(__name__)

@dataclass
class ABVariant:
    """Variant d'un test A/B"""
    variant_id: str
    title: str
    description: str
    tags: List[str]
    thumbnail_path: Optional[str] = None
    type: str = "control"  # control, treatment_1, treatment_2, etc.

@dataclass
class ABTestMetrics:
    """Métriques d'un test A/B"""
    impressions: int = 0
    clicks: int = 0
    views: int = 0
    watch_time_seconds: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    subscribers_gained: int = 0
    
    @property
    def ctr(self) -> float:
        """Click-through rate"""
        return (self.clicks / self.impressions) if self.impressions > 0 else 0.0
    
    @property
    def engagement_rate(self) -> float:
        """Taux d'engagement (likes + comments + shares) / views"""
        total_engagement = self.likes + self.comments + self.shares
        return (total_engagement / self.views) if self.views > 0 else 0.0
    
    @property
    def avg_watch_time(self) -> float:
        """Temps de visionnage moyen en secondes"""
        return (self.watch_time_seconds / self.views) if self.views > 0 else 0.0

@dataclass
class ABTest:
    """Test A/B complet"""
    test_id: str
    video_id: str
    created_at: datetime
    status: str  # active, completed, cancelled
    variants: Dict[str, ABVariant]
    metrics: Dict[str, ABTestMetrics]
    winner: Optional[str] = None
    confidence: Optional[float] = None
    duration_hours: int = 24
    
    def to_dict(self) -> Dict:
        """Convertir en dictionnaire pour sérialisation"""
        return {
            "test_id": self.test_id,
            "video_id": self.video_id,
            "created_at": self.created_at.isoformat(),
            "status": self.status,
            "variants": {k: asdict(v) for k, v in self.variants.items()},
            "metrics": {k: asdict(v) for k, v in self.metrics.items()},
            "winner": self.winner,
            "confidence": self.confidence,
            "duration_hours": self.duration_hours
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'ABTest':
        """Créer depuis un dictionnaire"""
        variants = {k: ABVariant(**v) for k, v in data["variants"].items()}
        metrics = {k: ABTestMetrics(**v) for k, v in data["metrics"].items()}
        
        return cls(
            test_id=data["test_id"],
            video_id=data["video_id"],
            created_at=datetime.fromisoformat(data["created_at"]),
            status=data["status"],
            variants=variants,
            metrics=metrics,
            winner=data.get("winner"),
            confidence=data.get("confidence"),
            duration_hours=data.get("duration_hours", 24)
        )

class ABTestManager:
    """Gestionnaire principal des tests A/B"""
    
    def __init__(self, storage_path: Path):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
    
    def create_test(self, video_id: str, base_metadata: Dict, 
                   trending_keywords: List[str] = None, 
                   duration_hours: int = 24) -> ABTest:
        """Créer un nouveau test A/B avec variants automatiques"""
        
        test_id = self._generate_test_id(video_id)
        
        # Générer les variants
        variants = self._generate_variants(base_metadata, trending_keywords or [])
        
        # Initialiser les métriques
        metrics = {variant_id: ABTestMetrics() for variant_id in variants.keys()}
        
        # Créer le test
        ab_test = ABTest(
            test_id=test_id,
            video_id=video_id,
            created_at=datetime.now(),
            status="active",
            variants=variants,
            metrics=metrics,
            duration_hours=duration_hours
        )
        
        # Sauvegarder
        self._save_test(ab_test)
        
        log.info(f"Test A/B créé: {test_id} avec {len(variants)} variants")
        return ab_test
    
    def _generate_test_id(self, video_id: str) -> str:
        """Générer un ID unique pour le test"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        hash_part = hashlib.md5(f"{video_id}_{timestamp}".encode()).hexdigest()[:8]
        return f"ab_{hash_part}_{timestamp}"
    
    def _generate_variants(self, base_metadata: Dict, trending_keywords: List[str]) -> Dict[str, ABVariant]:
        """Générer des variants pour le test A/B"""
        base_title = base_metadata.get("title", "")
        base_description = base_metadata.get("description", "")
        base_tags = base_metadata.get("tags", [])
        
        variants = {}
        
        # Variant de contrôle (original)
        variants["control"] = ABVariant(
            variant_id="control",
            title=base_title,
            description=base_description,
            tags=base_tags,
            type="control"
        )
        
        # Variant avec emoji
        if not self._has_emoji(base_title):
            emoji_title = self._add_emoji_to_title(base_title)
            variants["emoji"] = ABVariant(
                variant_id="emoji",
                title=emoji_title,
                description=base_description,
                tags=base_tags,
                type="emoji"
            )
        
        # Variant avec mot-clé tendance
        if trending_keywords:
            trending_title = self._add_trending_keyword(base_title, trending_keywords[0])
            trending_tags = base_tags + [trending_keywords[0]]
            
            variants["trending"] = ABVariant(
                variant_id="trending",
                title=trending_title,
                description=base_description,
                tags=trending_tags,
                type="trending"
            )
        
        # Variant avec question/curiosité
        curiosity_title = self._make_curiosity_title(base_title)
        variants["curiosity"] = ABVariant(
            variant_id="curiosity",
            title=curiosity_title,
            description=base_description,
            tags=base_tags,
            type="curiosity"
        )
        
        # Variant avec urgence/scarcité
        urgency_title = self._add_urgency_to_title(base_title)
        variants["urgency"] = ABVariant(
            variant_id="urgency",
            title=urgency_title,
            description=base_description,
            tags=base_tags,
            type="urgency"
        )
        
        return variants
    
    def _has_emoji(self, text: str) -> bool:
        """Vérifier si le texte contient des emojis"""
        return any(ord(char) > 127 for char in text)
    
    def _add_emoji_to_title(self, title: str) -> str:
        """Ajouter un emoji approprié au titre"""
        emoji_map = {
            "gaming": "🎮",
            "tech": "💻",
            "music": "🎵",
            "food": "🍳",
            "travel": "✈️",
            "fitness": "💪",
            "education": "📚",
            "comedy": "😂",
            "default": "🔥"
        }
        
        title_lower = title.lower()
        for category, emoji in emoji_map.items():
            if category in title_lower:
                return f"{emoji} {title}"
        
        return f"{emoji_map['default']} {title}"
    
    def _add_trending_keyword(self, title: str, keyword: str) -> str:
        """Ajouter un mot-clé tendance au titre"""
        if keyword.lower() in title.lower():
            return title
        
        # Essayer d'intégrer naturellement
        if len(title) + len(keyword) + 3 <= 60:
            return f"{title} - {keyword.title()}"
        
        return title
    
    def _make_curiosity_title(self, title: str) -> str:
        """Transformer le titre pour créer de la curiosité"""
        curiosity_patterns = [
            "Vous ne devinerez jamais: {}",
            "Le secret de {}",
            "Pourquoi {} va vous surprendre",
            "Ce que {} cache vraiment",
            "La vérité sur {}"
        ]
        
        # Choisir un pattern qui ne dépasse pas 60 caractères
        for pattern in curiosity_patterns:
            new_title = pattern.format(title)
            if len(new_title) <= 60:
                return new_title
        
        # Fallback: ajouter juste "Incroyable:"
        if len(title) + 12 <= 60:
            return f"Incroyable: {title}"
        
        return title
    
    def _add_urgency_to_title(self, title: str) -> str:
        """Ajouter de l'urgence au titre"""
        urgency_words = ["URGENT", "DERNIÈRE CHANCE", "MAINTENANT", "EXCLUSIF"]
        
        for word in urgency_words:
            new_title = f"{word}: {title}"
            if len(new_title) <= 60:
                return new_title
        
        return title
    
    def update_metrics(self, test_id: str, variant_id: str, metrics: ABTestMetrics):
        """Mettre à jour les métriques d'un variant"""
        test = self.get_test(test_id)
        if not test:
            log.error(f"Test introuvable: {test_id}")
            return
        
        test.metrics[variant_id] = metrics
        self._save_test(test)
        
        # Vérifier si le test doit être terminé
        self._check_test_completion(test)
    
    def get_test(self, test_id: str) -> Optional[ABTest]:
        """Récupérer un test par son ID"""
        test_file = self.storage_path / f"{test_id}.json"
        
        if not test_file.exists():
            return None
        
        try:
            with open(test_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return ABTest.from_dict(data)
        except Exception as e:
            log.error(f"Erreur lecture test {test_id}: {e}")
            return None
    
    def get_active_tests(self) -> List[ABTest]:
        """Récupérer tous les tests actifs"""
        active_tests = []
        
        for test_file in self.storage_path.glob("ab_*.json"):
            try:
                test = self.get_test(test_file.stem)
                if test and test.status == "active":
                    active_tests.append(test)
            except Exception as e:
                log.warning(f"Erreur lecture test {test_file}: {e}")
        
        return active_tests
    
    def _save_test(self, test: ABTest):
        """Sauvegarder un test"""
        test_file = self.storage_path / f"{test.test_id}.json"
        
        try:
            with open(test_file, 'w', encoding='utf-8') as f:
                json.dump(test.to_dict(), f, ensure_ascii=False, indent=2)
        except Exception as e:
            log.error(f"Erreur sauvegarde test {test.test_id}: {e}")
    
    def _check_test_completion(self, test: ABTest):
        """Vérifier si un test doit être terminé"""
        # Vérifier la durée
        elapsed = datetime.now() - test.created_at
        if elapsed.total_seconds() >= test.duration_hours * 3600:
            self._complete_test(test)
            return
        
        # Vérifier si on a assez de données pour une conclusion statistique
        total_views = sum(metrics.views for metrics.views in test.metrics.values())
        if total_views >= 1000:  # Seuil minimum pour analyse
            winner, confidence = self._calculate_winner(test)
            if confidence >= 0.95:  # 95% de confiance
                test.winner = winner
                test.confidence = confidence
                self._complete_test(test)
    
    def _calculate_winner(self, test: ABTest) -> Tuple[Optional[str], float]:
        """Calculer le variant gagnant avec niveau de confiance"""
        # Utiliser le CTR comme métrique principale
        variant_ctrs = {}
        
        for variant_id, metrics in test.metrics.items():
            if metrics.impressions > 0:
                variant_ctrs[variant_id] = metrics.ctr
        
        if len(variant_ctrs) < 2:
            return None, 0.0
        
        # Trouver le meilleur variant
        best_variant = max(variant_ctrs.items(), key=lambda x: x[1])
        
        # Calculer la confiance (simplifiée)
        # Dans un vrai système, utiliser des tests statistiques appropriés
        ctrs = list(variant_ctrs.values())
        ctrs.sort(reverse=True)
        
        if len(ctrs) >= 2:
            improvement = (ctrs[0] - ctrs[1]) / ctrs[1] if ctrs[1] > 0 else 0
            confidence = min(0.99, 0.5 + improvement * 2)  # Formule simplifiée
        else:
            confidence = 0.5
        
        return best_variant[0], confidence
    
    def _complete_test(self, test: ABTest):
        """Terminer un test"""
        test.status = "completed"
        
        if not test.winner:
            winner, confidence = self._calculate_winner(test)
            test.winner = winner
            test.confidence = confidence
        
        self._save_test(test)
        
        log.info(f"Test A/B terminé: {test.test_id}, gagnant: {test.winner} (confiance: {test.confidence:.2%})")
    
    def get_test_results(self, test_id: str) -> Optional[Dict]:
        """Obtenir les résultats détaillés d'un test"""
        test = self.get_test(test_id)
        if not test:
            return None
        
        results = {
            "test_id": test.test_id,
            "status": test.status,
            "winner": test.winner,
            "confidence": test.confidence,
            "variants": {}
        }
        
        for variant_id, variant in test.variants.items():
            metrics = test.metrics.get(variant_id, ABTestMetrics())
            
            results["variants"][variant_id] = {
                "title": variant.title,
                "type": variant.type,
                "metrics": {
                    "impressions": metrics.impressions,
                    "clicks": metrics.clicks,
                    "views": metrics.views,
                    "ctr": metrics.ctr,
                    "engagement_rate": metrics.engagement_rate,
                    "avg_watch_time": metrics.avg_watch_time
                }
            }
        
        return results
    
    def cleanup_old_tests(self, days_old: int = 30):
        """Nettoyer les anciens tests terminés"""
        cutoff_date = datetime.now() - timedelta(days=days_old)
        cleaned = 0
        
        for test_file in self.storage_path.glob("ab_*.json"):
            try:
                test = self.get_test(test_file.stem)
                if test and test.status == "completed" and test.created_at < cutoff_date:
                    test_file.unlink()
                    cleaned += 1
            except Exception as e:
                log.warning(f"Erreur nettoyage test {test_file}: {e}")
        
        if cleaned > 0:
            log.info(f"Nettoyage: {cleaned} anciens tests A/B supprimés")
        
        return cleaned

def create_ab_test_manager(config: Dict) -> Optional[ABTestManager]:
    """Créer un gestionnaire de tests A/B basé sur la configuration"""
    ab_config = config.get("ab_testing", {})
    
    if not ab_config.get("enabled", False):
        return None
    
    storage_path = Path(ab_config.get("storage_path", "./ab_tests"))
    
    try:
        return ABTestManager(storage_path)
    except Exception as e:
        log.error(f"Impossible de créer le gestionnaire A/B: {e}")
        return None
