"""
tge_radar.py — v1.8
Radar de détection des signaux précurseurs TGE/snapshot.

Analyse les signaux récents d'un projet et calcule un score
de probabilité TGE imminente (0-100) basé sur des patterns
observés historiquement sur des centaines d'airdrops.

Patterns détectés :
  - Tokenomics publiés
  - Audit smart contract annoncé/complété
  - Date de lancement mentionnée
  - "Last chance" / "Final" / urgence dans les communications
  - Activité inhabituelle (volume de tweets, fréquence annonces)
  - Mentions de CEX/listings
  - Fermeture de testnet annoncée
"""

import re
import logging
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


# ── Patterns pondérés par catégorie ─────────────────────────
# Score = somme des poids des patterns détectés, plafonné à 100

TGE_PATTERNS = {

    # Signaux forts (poids élevé)
    "tokenomics": {
        "weight": 25,
        "keywords": [
            "tokenomics", "token distribution", "token allocation",
            "vesting", "supply", "total supply", "circulating supply",
            "token economics", "distribution plan",
        ],
    },
    "audit": {
        "weight": 20,
        "keywords": [
            "audit", "audited", "certik", "hacken", "trail of bits",
            "security review", "smart contract audit", "audit completed",
            "audit passed",
        ],
    },
    "listing": {
        "weight": 25,
        "keywords": [
            "listing", "listed", "cex", "binance", "coinbase", "bybit",
            "okx", "kucoin", "gate.io", "huobi", "exchange listing",
            "trading starts", "trading begins", "market open",
        ],
    },
    "launch_date": {
        "weight": 30,
        "keywords": [
            "launch date", "tge date", "goes live", "mainnet launch",
            "q1", "q2", "q3", "q4", "january", "february", "march",
            "april", "may", "june", "july", "august", "september",
            "october", "november", "december", "this month", "next month",
            "coming soon", "very soon", "launching", "go live",
        ],
    },

    # Signaux d'urgence
    "urgency": {
        "weight": 20,
        "keywords": [
            "last chance", "final", "deadline", "ends soon", "closing",
            "last day", "hours left", "don't miss", "hurry", "limited time",
            "snapshot soon", "snapshot approaching", "cutoff",
        ],
    },
    "snapshot": {
        "weight": 30,
        "keywords": [
            "snapshot", "eligible", "eligibility", "airdrop criteria",
            "airdrop confirmed", "airdrop announced", "claim",
            "claimable", "distribution date", "airdrop date",
        ],
    },

    # Signaux de fin de testnet
    "testnet_end": {
        "weight": 20,
        "keywords": [
            "testnet ends", "testnet closing", "testnet complete",
            "end of testnet", "testnet phase complete", "mainnet migration",
            "moving to mainnet", "testnet rewards",
        ],
    },

    # Signaux d'activité communautaire intense
    "community_surge": {
        "weight": 10,
        "keywords": [
            "ama", "ask me anything", "community call", "town hall",
            "big announcement", "major update", "exciting news",
            "something big", "stay tuned", "announcement soon",
        ],
    },
}

SNAPSHOT_PATTERNS = {
    "direct": {
        "weight": 40,
        "keywords": [
            "snapshot", "snapshot taken", "snapshot complete",
            "eligibility check", "checking eligibility",
        ],
    },
    "criteria": {
        "weight": 25,
        "keywords": [
            "criteria", "requirements", "to be eligible", "must have",
            "qualify", "qualified users", "eligible addresses",
            "eligible wallets", "minimum transactions",
        ],
    },
    "deadline": {
        "weight": 35,
        "keywords": [
            "last day to", "deadline to", "must complete by",
            "before snapshot", "prior to snapshot", "ends in",
            "hours remaining", "days remaining",
        ],
    },
}


class TGERadar:
    """
    Analyse les signaux d'un projet et calcule un score TGE.
    Score 0-100 : probabilité d'un TGE/snapshot imminent.
    """

    def __init__(self, config: dict = None):
        self.config = config or {}

    def _scan_text(self, text: str, patterns: dict) -> dict:
        """
        Scanne un texte et retourne les patterns trouvés avec leurs poids.
        """
        text_lower = text.lower()
        found = {}

        for category, data in patterns.items():
            matched_keywords = [
                kw for kw in data["keywords"]
                if kw in text_lower
            ]
            if matched_keywords:
                found[category] = {
                    "weight":   data["weight"],
                    "keywords": matched_keywords,
                }

        return found

    def _calculate_score(self, found_patterns: dict) -> int:
        """Calcule le score en sommant les poids, plafonné à 100."""
        total = sum(p["weight"] for p in found_patterns.values())
        return min(total, 100)

    def analyze_signals(self, signals: list, project_name: str) -> dict:
        """
        Analyse une liste de signaux et retourne le rapport TGE.

        Args:
            signals      : liste de signaux de la DB (24-48h)
            project_name : nom du projet

        Returns:
            {
                tge_score       : int 0-100,
                snapshot_score  : int 0-100,
                risk_level      : "critical"|"high"|"medium"|"low",
                detected_patterns : dict,
                top_signals     : list,
                recommendation  : str,
            }
        """
        if not signals:
            return self._empty_report(project_name)

        # Combiner tous les contenus pour une analyse globale
        combined_text = " ".join(
            s.get("content", "") for s in signals
        )

        # Scanner TGE et snapshot séparément
        tge_found      = self._scan_text(combined_text, TGE_PATTERNS)
        snapshot_found = self._scan_text(combined_text, SNAPSHOT_PATTERNS)

        tge_score      = self._calculate_score(tge_found)
        snapshot_score = self._calculate_score(snapshot_found)

        # Score global = max des deux (on prend le pire cas)
        global_score = max(tge_score, snapshot_score)

        # Identifier les signaux les plus pertinents
        top_signals = sorted(
            signals,
            key=lambda s: s.get("urgency_score", 0),
            reverse=True
        )[:3]

        # Niveau de risque
        if global_score >= 70:
            risk_level = "critical"
        elif global_score >= 50:
            risk_level = "high"
        elif global_score >= 30:
            risk_level = "medium"
        else:
            risk_level = "low"

        # Recommandation contextuelle
        recommendation = self._build_recommendation(
            tge_score, snapshot_score, tge_found, snapshot_found, project_name
        )

        report = {
            "project_name":      project_name,
            "tge_score":         tge_score,
            "snapshot_score":    snapshot_score,
            "global_score":      global_score,
            "risk_level":        risk_level,
            "detected_patterns": {
                "tge":      tge_found,
                "snapshot": snapshot_found,
            },
            "top_signals":    [s.get("content", "") for s in top_signals],
            "recommendation": recommendation,
            "analyzed_at":    datetime.utcnow().isoformat(),
        }

        if global_score >= 30:
            logger.info(
                f"TGE Radar — {project_name} : score {global_score}/100 "
                f"[{risk_level.upper()}] — patterns: {list(tge_found.keys()) + list(snapshot_found.keys())}"
            )

        return report

    def _build_recommendation(
        self,
        tge_score: int,
        snapshot_score: int,
        tge_found: dict,
        snapshot_found: dict,
        project_name: str,
    ) -> str:
        """Génère une recommandation actionnable selon les patterns détectés."""

        if snapshot_score >= 60 or "snapshot" in snapshot_found or "direct" in snapshot_found:
            return (
                f"⚠️ SNAPSHOT PROBABLE IMMINENT sur {project_name}. "
                f"Vérifie ton éligibilité MAINTENANT et complète toutes les actions requises."
            )

        if "listing" in tge_found:
            return (
                f"🚨 Listing CEX détecté pour {project_name}. "
                f"TGE très proche — maximise ton engagement et vérifie les critères d'airdrop."
            )

        if "launch_date" in tge_found:
            return (
                f"📅 Date de lancement mentionnée pour {project_name}. "
                f"Intensifie ton engagement sur Twitter et Discord dès maintenant."
            )

        if "tokenomics" in tge_found or "audit" in tge_found:
            return (
                f"📊 Tokenomics/Audit détectés sur {project_name}. "
                f"TGE en préparation — reste actif et surveille les annonces de snapshot."
            )

        if "urgency" in tge_found or "deadline" in snapshot_found:
            return (
                f"⏰ Urgence détectée sur {project_name}. "
                f"Vérifie les deadlines et complète toutes les tâches en attente."
            )

        if tge_score >= 20:
            return (
                f"👀 Signaux TGE détectés sur {project_name}. "
                f"Reste attentif aux prochaines annonces."
            )

        return f"✅ Pas de signal TGE imminent sur {project_name}."

    def _empty_report(self, project_name: str) -> dict:
        return {
            "project_name":      project_name,
            "tge_score":         0,
            "snapshot_score":    0,
            "global_score":      0,
            "risk_level":        "low",
            "detected_patterns": {"tge": {}, "snapshot": {}},
            "top_signals":       [],
            "recommendation":    f"✅ Pas de signal TGE imminent sur {project_name}.",
            "analyzed_at":       datetime.utcnow().isoformat(),
        }

    def should_alert(self, report: dict, threshold: int = 40) -> bool:
        """Retourne True si le score dépasse le seuil d'alerte."""
        return report.get("global_score", 0) >= threshold
