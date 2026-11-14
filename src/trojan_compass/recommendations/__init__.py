"""Recommendation engine: grounded, stateless course/event recommendations.

Entry point: ``RecommendationEngine(repository, clock=...)``, which satisfies
``trojan_compass.contracts.RecommendationService``.
"""

from .clock import Clock, FixedClock, SystemClock
from .fake_repository import InMemoryGraphRepository, InterestLink
from .graph import GraphRepository
from .ranking import RankingPolicy
from .service import RecommendationEngine

__all__ = [
    "Clock",
    "FixedClock",
    "GraphRepository",
    "InMemoryGraphRepository",
    "InterestLink",
    "RankingPolicy",
    "RecommendationEngine",
    "SystemClock",
]
