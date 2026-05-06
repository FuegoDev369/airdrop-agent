"""
snapshot_engine.py — v1.8
Moteur de surveillance des critères d'éligibilité et alertes snapshot.

Croise les signaux collectés avec des heuristiques basées sur
les patterns historiques des grands airdrops (Arbitrum, Optimism,
zkSync, Starknet, Blur, etc.) pour estimer :
  - La probabilité d'un snapshot imminent
  - Les actions prioritaires à effectuer avant le snapshot
  - Le temps estimé restant

Patterns historiques intégrés :
  - Arbitrum : activité on-chain + ancienneté wallet
  - Optimism  : volume transactions + diversité protocoles
  - zkSync    : volume bridge + interactions contrats
  - MONAD     : engagement communautaire + testnet
  - Général   : tweets/jour, Discord roles, testnet txs
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


# ── Critères historiques par type de projet ──────────────────

AIRDROP_CRITERIA_TEMPLATES = {
    "L1_testnet": {
        "description": "L1 en phase testnet (ex: MONAD, DAC)",
        "criteria": [
            {
                "id":          "testnet_activity",
                "label":       "Activité testnet (transactions)",
                "description": "Envoyer des transactions sur le testnet",
                "weight":      30,
            },
            {
                "id":          "community_engagement",
                "label":       "Engagement communautaire",
                "description": "Tweets, Discord, Telegram actifs",
                "weight":      25,
            },
            {
                "id":          "early_user",
                "label":       "Utilisateur précoce",
                "description": "Avoir rejoint avant la fin du testnet",
                "weight":      20,
            },
            {
                "id":          "discord_roles",
                "label":       "Rôles Discord obtenus",
                "description": "Compléter les quêtes et obtenir des rôles",
                "weight":      15,
            },
            {
                "id":          "nft_mint",
                "label":       "NFT / Badge mintés",
                "description": "Minter les badges et NFTs du projet",
                "weight":      10,
            },
        ],
    },

    "L2_bridge": {
        "description": "L2 avec bridge (ex: Arbitrum, Optimism style)",
        "criteria": [
            {
                "id":          "bridge_volume",
                "label":       "Volume bridgé",
                "description": "Montant total bridgé vers le L2",
                "weight":      25,
            },
            {
                "id":          "tx_count",
                "label":       "Nombre de transactions",
                "description": "Transactions effectuées sur le L2",
                "weight":      25,
            },
            {
                "id":          "protocol_diversity",
                "label":       "Diversité des protocoles utilisés",
                "description": "Utiliser plusieurs DeFi protocols",
                "weight":      20,
            },
            {
                "id":          "wallet_age",
                "label":       "Ancienneté du wallet",
                "description": "Wallet actif depuis longtemps",
                "weight":      15,
            },
            {
                "id":          "unique_days",
                "label":       "Jours d'activité uniques",
                "description": "Actif sur plusieurs jours distincts",
                "weight":      15,
            },
        ],
    },

    "DeFi": {
        "description": "Protocole DeFi (ex: Berachain style)",
        "criteria": [
            {
                "id":          "liquidity_provision",
                "label":       "Liquidité fournie",
                "description": "Fournir de la liquidité aux pools",
                "weight":      30,
            },
            {
                "id":          "trading_volume",
                "label":       "Volume de trading",
                "description": "Volume total échangé sur le protocole",
                "weight":      25,
            },
            {
                "id":          "governance",
                "label":       "Participation gouvernance",
                "description": "Voter sur les propositions",
                "weight":      20,
            },
            {
                "id":          "staking",
                "label":       "Staking",
                "description": "Staker des tokens natifs",
                "weight":      25,
            },
        ],
    },
}


class SnapshotEngine:
    """
    Surveille les critères d'éligibilité et estime les délais snapshot.
    """

    def __init__(self, config: dict = None):
        self.config = config or {}

    def get_criteria_template(self, tags: list) -> dict:
        """
        Sélectionne le template de critères le plus adapté selon les tags du projet.
        """
        tags_lower = [t.lower() for t in (tags or [])]

        if "l1" in tags_lower and "testnet" in tags_lower:
            return AIRDROP_CRITERIA_TEMPLATES["L1_testnet"]
        elif "l2" in tags_lower or "bridge" in tags_lower:
            return AIRDROP_CRITERIA_TEMPLATES["L2_bridge"]
        elif "defi" in tags_lower:
            return AIRDROP_CRITERIA_TEMPLATES["DeFi"]
        else:
            # Défaut : L1 testnet (le plus fréquent dans le contexte actuel)
            return AIRDROP_CRITERIA_TEMPLATES["L1_testnet"]

    def estimate_snapshot_timing(
        self,
        tge_score: int,
        signals: list,
        tge_date: Optional[str] = None,
    ) -> dict:
        """
        Estime le délai avant snapshot selon les signaux disponibles.

        Returns:
            {
                days_estimate  : int ou None,
                confidence     : "high"|"medium"|"low",
                basis          : str (explication),
            }
        """
        # Si date TGE explicite dans la config
        if tge_date:
            try:
                tge_dt    = datetime.fromisoformat(tge_date)
                days_left = (tge_dt - datetime.utcnow()).days
                return {
                    "days_estimate": max(days_left, 0),
                    "confidence":    "high",
                    "basis":         f"Date TGE configurée : {tge_date}",
                }
            except ValueError:
                pass

        # Estimation basée sur le score TGE
        if tge_score >= 80:
            return {
                "days_estimate": 7,
                "confidence":    "medium",
                "basis":         "Score TGE très élevé — signaux forts d'imminence",
            }
        elif tge_score >= 60:
            return {
                "days_estimate": 14,
                "confidence":    "medium",
                "basis":         "Score TGE élevé — lancement probable < 2 semaines",
            }
        elif tge_score >= 40:
            return {
                "days_estimate": 30,
                "confidence":    "low",
                "basis":         "Signaux TGE modérés — lancement possible dans le mois",
            }
        elif tge_score >= 20:
            return {
                "days_estimate": 60,
                "confidence":    "low",
                "basis":         "Signaux faibles — surveillance recommandée",
            }
        else:
            return {
                "days_estimate": None,
                "confidence":    "low",
                "basis":         "Pas de signal TGE détecté",
            }

    def generate_action_checklist(
        self,
        project: dict,
        tge_score: int,
        days_estimate: Optional[int],
    ) -> list:
        """
        Génère une checklist d'actions prioritaires avant le snapshot.
        Adaptée selon l'urgence (jours restants estimés).
        """
        tags     = project.get("tags", [])
        template = self.get_criteria_template(tags)
        criteria = template.get("criteria", [])

        checklist = []

        for criterion in criteria:
            # Prioriser les actions selon l'urgence
            if days_estimate is not None and days_estimate <= 7:
                priority = "🔴 URGENT"
            elif days_estimate is not None and days_estimate <= 14:
                priority = "🟠 HAUTE"
            elif tge_score >= 40:
                priority = "🟡 MOYENNE"
            else:
                priority = "🟢 NORMALE"

            checklist.append({
                "id":          criterion["id"],
                "label":       criterion["label"],
                "description": criterion["description"],
                "weight":      criterion["weight"],
                "priority":    priority,
            })

        # Trier par poids décroissant
        return sorted(checklist, key=lambda x: x["weight"], reverse=True)

    def build_report(
        self,
        project: dict,
        signals: list,
        tge_radar_report: dict,
    ) -> dict:
        """
        Construit le rapport complet d'éligibilité pour un projet.

        Args:
            project          : dict projet depuis la DB
            signals          : signaux récents (24-48h)
            tge_radar_report : rapport du TGERadar

        Returns:
            rapport complet avec checklist, timing, recommandations
        """
        tge_score    = tge_radar_report.get("global_score", 0)
        tge_date     = project.get("tge_date")
        project_name = project.get("name", "")
        tags         = project.get("tags", [])

        # Timing estimé
        timing = self.estimate_snapshot_timing(tge_score, signals, tge_date)

        # Checklist d'actions
        checklist = self.generate_action_checklist(
            project, tge_score, timing.get("days_estimate")
        )

        # Template de critères applicable
        template = self.get_criteria_template(tags)

        report = {
            "project_name":  project_name,
            "tge_score":     tge_score,
            "risk_level":    tge_radar_report.get("risk_level", "low"),
            "timing":        timing,
            "template_used": template["description"],
            "checklist":     checklist,
            "recommendation": tge_radar_report.get("recommendation", ""),
            "generated_at":  datetime.utcnow().isoformat(),
        }

        logger.info(
            f"SnapshotEngine — {project_name} : "
            f"délai estimé {timing.get('days_estimate', '?')} jours | "
            f"confiance {timing.get('confidence', '?')}"
        )

        return report

    def format_notification(self, report: dict) -> str:
        """
        Formate le rapport en message Telegram/Discord lisible.
        """
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

        days = timing.get("days_estimate")
        days_str = f"~{days} jours" if days else "indéterminé"

        lines = [
            f"📊 <b>Rapport Snapshot — {project_name}</b>",
            f"",
            f"{risk_emoji} Score TGE : <b>{tge_score}/100</b> [{risk_level.upper()}]",
            f"📅 Snapshot estimé : <b>{days_str}</b> ({timing.get('confidence', '?')} confiance)",
            f"",
            f"✅ <b>Actions prioritaires :</b>",
        ]

        for action in checklist:
            lines.append(f"  {action['priority']} {action['label']}")
            lines.append(f"     → {action['description']}")

        lines.append("")
        lines.append(f"💡 {report.get('recommendation', '')}")

        return "\n".join(lines)
