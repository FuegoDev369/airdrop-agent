"""
tge_radar.py — v1.9.1
TGE/snapshot precursor signal detection radar.

Analyzes recent signals from a project and computes a TGE probability
score (0-100) based on patterns historically observed across hundreds
of airdrops (Arbitrum, Optimism, zkSync, Starknet, MONAD, etc.).

Detected pattern categories:
  - Tokenomics published
  - Smart contract audit announced/completed
  - Launch date mentioned
  - "Last chance" / "Final" / urgency in communications
  - CEX listing announced
  - Testnet closure announced
  - Snapshot directly mentioned

CHANGELOG v1.9.1:
  - Full translation to English (comments, docstrings, strings)
  - No functional changes from v1.8
"""

import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


# ── Weighted patterns by category ────────────────────────────
# Score = sum of matched pattern weights, capped at 100

TGE_PATTERNS = {

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
    "testnet_end": {
        "weight": 20,
        "keywords": [
            "testnet ends", "testnet closing", "testnet complete",
            "end of testnet", "testnet phase complete", "mainnet migration",
            "moving to mainnet", "testnet rewards",
        ],
    },
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
    Analyzes project signals and computes a TGE probability score.
    Score 0-100: probability of an imminent TGE or snapshot.
    """

    def __init__(self, config: dict = None):
        self.config = config or {}

    def _scan_text(self, text: str, patterns: dict) -> dict:
        """Scan text and return matched patterns with their weights."""
        text_lower = text.lower()
        found = {}

        for category, data in patterns.items():
            matched = [kw for kw in data["keywords"] if kw in text_lower]
            if matched:
                found[category] = {
                    "weight":   data["weight"],
                    "keywords": matched,
                }

        return found

    def _calculate_score(self, found_patterns: dict) -> int:
        """Sum matched pattern weights, capped at 100."""
        total = sum(p["weight"] for p in found_patterns.values())
        return min(total, 100)

    def analyze_signals(self, signals: list, project_name: str) -> dict:
        """
        Analyze a list of signals and return a TGE report.

        Args:
            signals      : list of DB signals (24-48h window)
            project_name : project name for logging

        Returns:
            {
                tge_score         : int 0-100,
                snapshot_score    : int 0-100,
                global_score      : int 0-100,
                risk_level        : "critical"|"high"|"medium"|"low",
                detected_patterns : dict,
                top_signals       : list,
                recommendation    : str,
                analyzed_at       : str (ISO datetime),
            }
        """
        if not signals:
            return self._empty_report(project_name)

        combined_text  = " ".join(s.get("content", "") for s in signals)
        tge_found      = self._scan_text(combined_text, TGE_PATTERNS)
        snapshot_found = self._scan_text(combined_text, SNAPSHOT_PATTERNS)

        tge_score      = self._calculate_score(tge_found)
        snapshot_score = self._calculate_score(snapshot_found)
        global_score   = max(tge_score, snapshot_score)

        top_signals = sorted(
            signals, key=lambda s: s.get("urgency_score", 0), reverse=True
        )[:3]

        if global_score >= 70:   risk_level = "critical"
        elif global_score >= 50: risk_level = "high"
        elif global_score >= 30: risk_level = "medium"
        else:                    risk_level = "low"

        recommendation = self._build_recommendation(
            tge_score, snapshot_score, tge_found, snapshot_found, project_name
        )

        report = {
            "project_name":      project_name,
            "tge_score":         tge_score,
            "snapshot_score":    snapshot_score,
            "global_score":      global_score,
            "risk_level":        risk_level,
            "detected_patterns": {"tge": tge_found, "snapshot": snapshot_found},
            "top_signals":       [s.get("content", "") for s in top_signals],
            "recommendation":    recommendation,
            "analyzed_at":       datetime.utcnow().isoformat(),
        }

        if global_score >= 30:
            logger.info(
                f"TGE Radar — {project_name}: score {global_score}/100 "
                f"[{risk_level.upper()}] — patterns: "
                f"{list(tge_found.keys()) + list(snapshot_found.keys())}"
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
        """Generate an actionable recommendation based on detected patterns."""

        if snapshot_score >= 60 or "snapshot" in snapshot_found or "direct" in snapshot_found:
            return (
                f"⚠️ PROBABLE IMMINENT SNAPSHOT on {project_name}. "
                f"Verify your eligibility NOW and complete all required actions."
            )
        if "listing" in tge_found:
            return (
                f"🚨 CEX listing detected for {project_name}. "
                f"TGE very close — maximize engagement and check airdrop criteria."
            )
        if "launch_date" in tge_found:
            return (
                f"📅 Launch date mentioned for {project_name}. "
                f"Intensify Twitter and Discord engagement immediately."
            )
        if "tokenomics" in tge_found or "audit" in tge_found:
            return (
                f"📊 Tokenomics/Audit detected on {project_name}. "
                f"TGE in preparation — stay active and watch for snapshot announcements."
            )
        if "urgency" in tge_found or "deadline" in snapshot_found:
            return (
                f"⏰ Urgency signals detected on {project_name}. "
                f"Check deadlines and complete all pending tasks."
            )
        if tge_score >= 20:
            return (
                f"👀 TGE signals detected on {project_name}. "
                f"Stay alert for upcoming announcements."
            )
        return f"✅ No imminent TGE signal on {project_name}."

    def _empty_report(self, project_name: str) -> dict:
        return {
            "project_name":      project_name,
            "tge_score":         0,
            "snapshot_score":    0,
            "global_score":      0,
            "risk_level":        "low",
            "detected_patterns": {"tge": {}, "snapshot": {}},
            "top_signals":       [],
            "recommendation":    f"✅ No imminent TGE signal on {project_name}.",
            "analyzed_at":       datetime.utcnow().isoformat(),
        }

    def should_alert(self, report: dict, threshold: int = 40) -> bool:
        """Return True if the global score exceeds the alert threshold."""
        return report.get("global_score", 0) >= threshold
