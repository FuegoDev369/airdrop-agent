"""
wallet_scorer.py — v1.8.1
Estimateur de score wallet et position dans la distribution d'airdrop.

CHANGELOG v1.8.1 :
  - SÉCURITÉ : wallets lus UNIQUEMENT depuis variables d'environnement
    (GitHub Secrets ou fichier .env local)
  - Suppression du champ "wallets" dans settings.yaml
  - Jamais d'adresse wallet dans le code source ou la config
"""

import os
import logging
import requests
from typing import Optional

logger = logging.getLogger(__name__)

PUBLIC_RPCS = {
    "ethereum":  "https://eth.llamarpc.com",
    "arbitrum":  "https://arb1.arbitrum.io/rpc",
    "optimism":  "https://mainnet.optimism.io",
    "base":      "https://mainnet.base.org",
    "polygon":   "https://polygon-rpc.com",
    "bsc":       "https://bsc-dataseed.binance.org",
    "avalanche": "https://api.avax.network/ext/bc/C/rpc",
}


class WalletScorer:
    def __init__(self, config: dict = None):
        self.config  = config or {}
        self.wallets = self._load_wallets_from_env()
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

    def _load_wallets_from_env(self) -> list:
        """
        Charge les adresses wallet UNIQUEMENT depuis les variables d'environnement.

        Sources (par ordre de priorité) :
          1. WALLET_ADDRESSES dans GitHub Secrets (production)
          2. WALLET_ADDRESSES dans fichier .env local (développement Termux)

        Format : adresses séparées par des virgules
          WALLET_ADDRESSES=0xAdresse1,0xAdresse2,0xAdresse3

        NE PAS mettre les adresses dans settings.yaml — ce fichier
        est public sur GitHub.
        """
        raw = os.environ.get("WALLET_ADDRESSES", "").strip()

        if not raw:
            logger.info(
                "WalletScorer : aucun wallet configuré. "
                "Ajoute WALLET_ADDRESSES dans GitHub Secrets ou dans .env"
            )
            return []

        wallets = [
            w.strip().lower()
            for w in raw.split(",")
            if w.strip().startswith("0x") and len(w.strip()) == 42
        ]

        invalid = [
            w.strip()
            for w in raw.split(",")
            if w.strip() and not (w.strip().startswith("0x") and len(w.strip()) == 42)
        ]
        if invalid:
            logger.warning(
                f"WalletScorer : {len(invalid)} adresse(s) ignorée(s) "
                f"(format invalide — doit commencer par 0x et faire 42 caractères)"
            )

        if wallets:
            # Log uniquement les 6 premiers + 4 derniers chars — jamais l'adresse complète
            masked = [f"{w[:6]}...{w[-4:]}" for w in wallets]
            logger.info(f"WalletScorer : {len(wallets)} wallet(s) chargé(s) : {masked}")

        return wallets

    def _rpc_call(self, rpc_url: str, method: str, params: list) -> Optional[str]:
        payload = {
            "jsonrpc": "2.0",
            "method":  method,
            "params":  params,
            "id":      1,
        }
        try:
            resp = self.session.post(rpc_url, json=payload, timeout=10)
            resp.raise_for_status()
            return resp.json().get("result")
        except Exception as e:
            logger.debug(f"RPC {rpc_url} — {method} : {e}")
            return None

    def get_tx_count(self, wallet: str, chain: str) -> Optional[int]:
        rpc = PUBLIC_RPCS.get(chain.lower())
        if not rpc:
            return None
        result = self._rpc_call(rpc, "eth_getTransactionCount", [wallet, "latest"])
        try:
            return int(result, 16) if result else None
        except (ValueError, TypeError):
            return None

    def get_balance(self, wallet: str, chain: str) -> Optional[float]:
        rpc = PUBLIC_RPCS.get(chain.lower())
        if not rpc:
            return None
        result = self._rpc_call(rpc, "eth_getBalance", [wallet, "latest"])
        try:
            return int(result, 16) / 1e18 if result else None
        except (ValueError, TypeError):
            return None

    def _normalize_chain(self, chain: str) -> Optional[str]:
        mapping = {
            "eth": "ethereum", "ethereum": "ethereum", "mainnet": "ethereum",
            "arb": "arbitrum", "arbitrum": "arbitrum", "arbitrum one": "arbitrum",
            "op": "optimism", "optimism": "optimism",
            "base": "base",
            "matic": "polygon", "polygon": "polygon",
            "bnb": "bsc", "bsc": "bsc",
            "avax": "avalanche", "avalanche": "avalanche",
        }
        return mapping.get(chain.lower())

    def analyze_wallet_for_project(self, wallet: str, project: dict) -> dict:
        chain            = project.get("chain", "ethereum").lower()
        chain_normalized = self._normalize_chain(chain)
        masked_wallet    = f"{wallet[:6]}...{wallet[-4:]}"

        activity = {
            "wallet":       masked_wallet,  # Jamais l'adresse complète dans les logs
            "project":      project.get("name", ""),
            "chain":        chain,
            "tags":         project.get("tags", []),
            "tx_count":     None,
            "balance":      None,
            "data_sources": [],
        }

        if chain_normalized and chain_normalized in PUBLIC_RPCS:
            tx_count = self.get_tx_count(wallet, chain_normalized)
            balance  = self.get_balance(wallet, chain_normalized)
            if tx_count is not None:
                activity["tx_count"]     = tx_count
                activity["data_sources"].append(f"tx_count via {chain_normalized} RPC")
            if balance is not None:
                activity["balance"]      = round(balance, 6)
                activity["data_sources"].append(f"balance via {chain_normalized} RPC")
        else:
            logger.info(f"WalletScorer : chain '{chain}' non supportée — analyse LLM uniquement")

        return activity

    def _basic_score(self, activity: dict) -> dict:
        tx_count = activity.get("tx_count") or 0
        balance  = activity.get("balance")  or 0.0
        score    = 0

        if tx_count > 100:   score += 40
        elif tx_count > 50:  score += 25
        elif tx_count > 10:  score += 15
        elif tx_count > 0:   score += 5

        if balance > 1.0:    score += 30
        elif balance > 0.1:  score += 15
        elif balance > 0.01: score += 5

        tier = (
            "top_20pct" if score >= 60 else
            "eligible"  if score >= 40 else
            "low"       if score >= 20 else
            "unknown"
        )
        return {
            "score_estimate":      min(score, 100),
            "tier":                tier,
            "strengths":           [f"{tx_count} transactions on-chain"] if tx_count else [],
            "weaknesses":          ["Données limitées sans LLM"],
            "recommended_actions": ["Augmenter l'activité on-chain"],
        }

    def score_all_wallets(self, project: dict, llm=None) -> list:
        if not self.wallets:
            return []

        reports = []
        for wallet in self.wallets:
            try:
                activity     = self.analyze_wallet_for_project(wallet, project)
                score_report = llm.score_wallet_eligibility(project["name"], activity) if llm else self._basic_score(activity)
                score_report["wallet"]   = f"{wallet[:6]}...{wallet[-4:]}"  # Masqué
                score_report["activity"] = activity
                reports.append(score_report)
                logger.info(
                    f"Wallet {wallet[:6]}...{wallet[-4:]} — {project['name']} : "
                    f"score {score_report.get('score_estimate', '?')}/100 [{score_report.get('tier', '?')}]"
                )
            except Exception as e:
                logger.warning(f"Erreur scoring wallet {wallet[:6]}... : {e}")

        return reports

    def format_notification(self, reports: list, project_name: str) -> str:
        if not reports:
            return (
                f"💼 Wallet Scoring — {project_name}\n\n"
                f"Aucun wallet configuré.\n"
                f"Ajoute <code>WALLET_ADDRESSES</code> dans GitHub Secrets."
            )

        tier_emoji = {
            "top_1pct": "🏆", "top_5pct": "🥇", "top_20pct": "🥈",
            "eligible": "✅", "low": "⚠️", "unknown": "❓",
        }
        lines = [f"💼 <b>Wallet Scoring — {project_name}</b>\n"]

        for r in reports:
            emoji   = tier_emoji.get(r.get("tier", "unknown"), "❓")
            actions = r.get("recommended_actions", [])
            lines.append(f"{emoji} <code>{r.get('wallet', '???')}</code>")
            lines.append(f"   Score : <b>{r.get('score_estimate', 0)}/100</b> | {r.get('tier', '?')}")
            if actions:
                lines.append(f"   → {actions[0]}")
            lines.append("")

        return "\n".join(lines)
