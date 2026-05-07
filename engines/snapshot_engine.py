"""
snapshot_engine.py — v1.9.1
Eligibility criteria monitoring and snapshot alert engine.

Crosses collected signals with heuristics based on historical patterns
from major airdrops (Arbitrum, Optimism, zkSync, Starknet, Blur, MONAD)
to estimate:
  - Probability of an imminent snapshot
  - Priority actions to complete before the snapshot
  - Estimated time remaining

Historical patterns integrated:
  - Arbitrum : on-chain activity + wallet age
  - Optimism  : transaction volume + protocol diversity
  - zkSync    : bridge volume + contract interactions
  - MONAD     : community engagement + testnet activity
  - General   : tweets/day, Discord roles, testnet transactions

CHANGELOG v1.9.1:
  - Full translation to English (comments, docstrings, strings)
  - No functional changes from v1.8
"""

import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


# ── Criteria templates by project type ───────────────────────

AIRDROP_CRITERIA_TEMPLATES = {
    "L1_testnet": {
        "description": "L1 in testnet phase (e.g. MONAD, DAC)",
        "criteria": [
            {
                "id":          "testnet_activity",
                "label":       "Testnet activity (transactions)",
                "description": "Send transactions on the testnet",
                "weight":      30,
            },
            {
                "id":          "community_engagement",
                "label":       "Community engagement",
                "description": "Active on Twitter, Discord, Telegram",
                "weight":      25,
            },
            {
                "id":          "early_user",
                "label":       "Early user",
                "description": "Joined before end of testnet phase",
                "weight":      20,
            },
            {
                "id":          "discord_roles",
                "label":       "Discord roles obtained",
                "description": "Complete quests and earn roles",
                "weight":      15,
            },
            {
                "id":          "nft_mint",
                "label":       "NFTs / Badges minted",
                "description": "Mint project badges and NFTs",
                "weight":      10,
            },
        ],
    },

    "L2_bridge": {
        "description": "L2 with bridge (e.g. Arbitrum, Optimism style)",
        "criteria": [
            {
                "id":          "bridge_volume",
                "label":       "Bridged volume",
                "description": "Total amount bridged to the L2",
                "weight":      25,
            },
            {
                "id":          "tx_count",
                "label":       "Transaction count",
                "description": "Transactions executed on the L2",
                "weight":      25,
            },
            {
                "id":          "protocol_diversity",
                "label":       "Protocol diversity",
                "description": "Interact with multiple DeFi protocols",
                "weight":      20,
            },
            {
                "id":          "wallet_age",
                "label":       "Wallet age",
                "description": "Wallet active for a significant period",
                "weight":      15,
            },
            {
                "id":          "unique_days",
                "label":       "Unique active days",
                "description": "Active on multiple distinct days",
                "weight":      15,
            },
        ],
    },

    "DeFi": {
        "description": "DeFi protocol (e.g. Berachain style)",
        "criteria": [
            {
                "id":          "liquidity_provision",
                "label":       "Liquidity provided",
                "description": "Provide liquidity to pools",
                "weight":      30,
            },
            {
                "id":          "trading_volume",
                "label":       "Trading volume",
                "description": "Total volume swapped on the protocol",
                "weight":      25,
            },
            {
                "id":          "governance",
                "label":       "Governance participation",
                "description": "Vote on proposals",
                "weight":      20,
            },
            {
                "id":          "staking",
                "label":       "Staking",
                "description": "Stake native tokens",
                "weight":      25,
            },
        ],
    },
}


class SnapshotEngine:
    """
    Monitors eligibility criteria and estimates snapshot timing.
    """

    def __init__(self, config: dict = None):
        self.config = config or {}

    def get_criteria_template(self, tags: list) -> dict:
        """Select the most appropriate criteria template based on project tags."""
        tags_lower = [t.lower() for t in (tags or [])]

        if "l1" in tags_lower and "testnet" in tags_lower:
            return AIRDROP_CRITERIA_TEMPLATES["L1_testnet"]
        elif "l2" in tags_lower or "bridge" in tags_lower:
            return AIRDROP_CRITERIA_TEMPLATES["L2_bridge"]
        elif "defi" in tags_lower:
            return AIRDROP_CRITERIA_TEMPLATES["DeFi"]
        else:
            # Default: L1 testnet (most common in current context)
            return AIRDROP_CRITERIA_TEMPLATES["L1_testnet"]

    def estimate_snapshot_timing(
        self,
        tge_score: int,
        signals: list,
        tge_date: Optional[str] = None,
    ) -> dict:
        """
        Estimate time to snapshot based on available signals.

        Returns:
            {
                days_estimate : int or None,
                confidence    : "high"|"medium"|"low",
                basis         : str (explanation),
            }
        """
        # Use explicit TGE date if configured
        if tge_date:
            try:
                tge_dt    = datetime.fromisoformat(tge_date)
                days_left = (tge_dt - datetime.utcnow()).days
                return {
                    "days_estimate": max(days_left, 0),
                    "confidence":    "high",
                    "basis":         f"TGE date configured: {tge_date}",
                }
            except ValueError:
                pass

        # Estimate from TGE score
        if tge_score >= 80:
            return {
                "days_estimate": 7,
                "confidence":    "medium",
                "basis":         "Very high TGE score — strong imminence signals",
            }
        elif tge_score >= 60:
            return {
                "days_estimate": 14,
                "confidence":    "medium",
                "basis":         "High TGE score — probable launch within 2 weeks",
            }
        elif tge_score >= 40:
            return {
                "days_estimate": 30,
                "confidence":    "low",
                "basis":         "Moderate TGE signals — possible launch within the month",
            }
        elif tge_score >= 20:
            return {
                "days_estimate": 60,
                "confidence":    "low",
                "basis":         "Weak signals — continued monitoring recommended",
            }
        else:
            return {
                "days_estimate": None,
                "confidence":    "low",
                "basis":         "No TGE signal detected",
            }

    def generate_action_checklist(
        self,
        project: dict,
        tge_score: int,
        days_estimate: Optional[int],
    ) -> list:
        """
        Generate a prioritized action checklist before the snapshot.
        Adapted based on urgency (estimated days remaining).
        """
        tags      = project.get("tags", [])
        template  = self.get_criteria_template(tags)
        criteria  = template.get("criteria", [])
        checklist = []

        for criterion in criteria:
            if days_estimate is not None and days_estimate <= 7:
                priority = "🔴 URGENT"
            elif days_estimate is not None and days_estimate <= 14:
                priority = "🟠 HIGH"
            elif tge_score >= 40:
                priority = "🟡 MEDIUM"
            else:
                priority = "🟢 NORMAL"

            checklist.append({
                "id":          criterion["id"],
                "label":       criterion["label"],
                "description": criterion["description"],
                "weight":      criterion["weight"],
                "priority":    priority,
            })

        return sorted(checklist, key=lambda x: x["weight"], reverse=True)

    def build_report(
        self,
        project: dict,
        signals: list,
        tge_radar_report: dict,
    ) -> dict:
        """
        Build the complete eligibility report for a project.

        Args:
            project          : project dict from DB
            signals          : recent signals (24-48h window)
            tge_radar_report : report from TGERadar.analyze_signals()

        Returns:
            complete report with checklist, timing, and recommendations
        """
        tge_score    = tge_radar_report.get("global_score", 0)
        tge_date     = project.get("tge_date")
        project_name = project.get("name", "")
        tags         = project.get("tags", [])

        timing    = self.estimate_snapshot_timing(tge_score, signals, tge_date)
        checklist = self.generate_action_checklist(
            project, tge_score, timing.get("days_estimate")
        )
        template  = self.get_criteria_template(tags)

        report = {
            "project_name":   project_name,
            "tge_score":      tge_score,
            "risk_level":     tge_radar_report.get("risk_level", "low"),
            "timing":         timing,
            "template_used":  template["description"],
            "checklist":      checklist,
            "recommendation": tge_radar_report.get("recommendation", ""),
            "generated_at":   datetime.utcnow().isoformat(),
        }

        logger.info(
            f"SnapshotEngine — {project_name}: "
            f"estimated {timing.get('days_estimate', '?')} days | "
            f"confidence: {timing.get('confidence', '?')}"
        )

        return report

    def format_notification(self, report: dict) -> str:
        """Format the report as a readable Telegram/Discord message."""
        project_name = report["project_name"]
        tge_score    = report["tge_score"]
        risk_level   = report["risk_level"]
        timing       = report["timing"]
        checklist    = report["checklist"][:4]  # Top 4 actions

        risk_emoji = {
            "critical": "🔴",
            "high":     "🟠",
            "medium":   "🟡",
            "low":      "🟢",
        }.get(risk_level, "⚪")

        days     = timing.get("days_estimate")
        days_str = f"~{days} days" if days else "unknown"

        lines = [
            f"📊 <b>Snapshot Report — {project_name}</b>",
            f"",
            f"{risk_emoji} TGE Score: <b>{tge_score}/100</b> [{risk_level.upper()}]",
            f"📅 Estimated snapshot: <b>{days_str}</b> ({timing.get('confidence', '?')} confidence)",
            f"",
            f"✅ <b>Priority actions:</b>",
        ]

        for action in checklist:
            lines.append(f"  {action['priority']} {action['label']}")
            lines.append(f"     → {action['description']}")

        lines.append("")
        lines.append(f"💡 {report.get('recommendation', '')}")

        return "\n".join(lines)
