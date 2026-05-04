"""
llm_engine.py
Interface unifiée LLM — switch Groq (cloud) / Ollama (local)
selon la configuration dans settings.yaml
"""

import os
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class LLMEngine:
    def __init__(self, config: dict):
        self.mode = config["llm"]["mode"]
        self.cfg = config["llm"][self.mode]
        self._client = None
        logger.info(f"LLM Engine initialisé en mode : {self.mode}")

    def _get_groq_client(self):
        if self._client is None:
            try:
                from groq import Groq
                api_key = os.environ.get("GROQ_API_KEY")
                if not api_key:
                    raise ValueError("GROQ_API_KEY manquant dans les variables d'environnement")
                self._client = Groq(api_key=api_key)
            except ImportError:
                raise ImportError("Package 'groq' manquant. Lance : pip install groq")
        return self._client

    def _call_groq(self, prompt: str, system: str = "") -> str:
        client = self._get_groq_client()
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        response = client.chat.completions.create(
            model=self.cfg["model"],
            messages=messages,
            max_tokens=self.cfg["max_tokens"],
            temperature=self.cfg["temperature"],
        )
        return response.choices[0].message.content.strip()

    def _call_ollama(self, prompt: str, system: str = "") -> str:
        try:
            import requests
            payload = {
                "model": self.cfg["model"],
                "prompt": prompt,
                "system": system,
                "stream": False,
                "options": {
                    "temperature": self.cfg["temperature"],
                    "num_predict": self.cfg["max_tokens"],
                }
            }
            resp = requests.post(
                f"{self.cfg['base_url']}/api/generate",
                json=payload,
                timeout=120
            )
            resp.raise_for_status()
            return resp.json()["response"].strip()
        except ImportError:
            raise ImportError("Package 'requests' manquant. Lance : pip install requests")

    def call(self, prompt: str, system: str = "") -> str:
        """Appel LLM unifié — utilise le backend configuré."""
        try:
            if self.mode == "groq":
                return self._call_groq(prompt, system)
            elif self.mode == "ollama":
                return self._call_ollama(prompt, system)
            else:
                raise ValueError(f"Mode LLM inconnu : {self.mode}")
        except Exception as e:
            logger.error(f"Erreur LLM ({self.mode}) : {e}")
            raise

    # ── Méthodes spécialisées ────────────────────────────────

    def classify_signal(self, content: str, project_name: str) -> dict:
        """
        Classifie un signal et lui attribue un score d'urgence.
        Retourne: { signal_type, urgency_score, summary, action_required }
        """
        system = """Tu es un analyste expert en projets Web3 et airdrops crypto.
Tu analyses des signaux (tweets, annonces, messages Discord/Telegram) pour un tracker d'airdrop.
Tu réponds UNIQUEMENT en JSON valide, sans markdown, sans explication."""

        prompt = f"""Analyse ce signal pour le projet "{project_name}" :

CONTENU : {content[:1500]}

Retourne exactement ce JSON :
{{
  "signal_type": "quest|snapshot|tge_signal|major_announcement|regular_update|hype|irrelevant",
  "urgency_score": <entier 1-10>,
  "summary": "<résumé en 1 phrase max>",
  "action_required": "<action concrète suggérée ou null>",
  "keywords": ["<mot-clé1>", "<mot-clé2>"]
}}

Règles de scoring urgence :
- 9-10 : snapshot imminent, TGE annoncé, quête qui expire < 24h
- 7-8  : nouvelle quête, annonce majeure, nouveau testnet
- 5-6  : mise à jour importante, partenariat
- 3-4  : update régulière, contenu informatif
- 1-2  : hype générale, bruit, non pertinent"""

        try:
            response = self.call(prompt, system)
            # Nettoyer les éventuels backticks markdown
            clean = response.strip().strip("```json").strip("```").strip()
            return json.loads(clean)
        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"Erreur classification signal : {e}")
            return {
                "signal_type": "regular_update",
                "urgency_score": 3,
                "summary": content[:100],
                "action_required": None,
                "keywords": []
            }

    def generate_tweet(self, project_name: str, context: str, language: str = "fr") -> str:
        """Génère un tweet authentique et engagé pour un projet."""
        lang_instruction = "en français" if language == "fr" else "in English"

        system = f"""Tu es un vrai membre passionné de la communauté Web3.
Tu génères des tweets authentiques {lang_instruction}, jamais génériques.
Tes tweets montrent une vraie compréhension du projet.
Tu n'utilises JAMAIS de hashtags spam. Maximum 2 hashtags pertinents.
Tu réponds uniquement avec le texte du tweet, sans guillemets."""

        prompt = f"""Génère un tweet engagé pour le projet "{project_name}".

Contexte récent du projet :
{context[:800]}

Contraintes :
- Maximum 260 caractères
- Ton authentique, pas corporate
- Montre une vraie connaissance du projet
- Peut inclure une question pour engager la communauté
- 1-2 hashtags maximum et pertinents"""

        return self.call(prompt, system)

    def generate_daily_brief(self, projects_data: list) -> str:
        """Génère un briefing quotidien structuré pour tous les projets."""
        system = """Tu es l'assistant d'un airdrop farmer sérieux.
Tu génères des briefings clairs, actionnables et priorisés.
Tu es direct et concis. Tu réponds en français."""

        projects_summary = json.dumps(projects_data, ensure_ascii=False, indent=2)

        prompt = f"""Génère un briefing quotidien basé sur ces données de projets :

{projects_summary[:2000]}

Structure ton briefing ainsi :
1. 🔴 URGENT (actions < 24h)
2. 🟡 AUJOURD'HUI (actions recommandées)
3. 🟢 VEILLE (rien d'urgent)
4. 💡 CONSEIL DU JOUR (1 tip stratégique)

Sois concis et actionnable."""

        return self.call(prompt, system)

    def score_wallet_eligibility(self, project_name: str, wallet_activity: dict) -> dict:
        """Estime le score d'éligibilité d'un wallet pour un airdrop."""
        system = """Tu es un expert en tokenomics et critères d'éligibilité airdrop.
Tu analyses l'activité d'un wallet et estimes sa position probable dans une distribution.
Tu réponds en JSON uniquement."""

        prompt = f"""Estime l'éligibilité de ce wallet pour l'airdrop de "{project_name}" :

Activité wallet : {json.dumps(wallet_activity, ensure_ascii=False)}

Retourne :
{{
  "score_estimate": <0-100>,
  "tier": "top_1pct|top_5pct|top_20pct|eligible|low|unknown",
  "strengths": ["<point fort>"],
  "weaknesses": ["<point faible>"],
  "recommended_actions": ["<action pour améliorer>"]
}}"""

        try:
            response = self.call(prompt, system)
            clean = response.strip().strip("```json").strip("```").strip()
            return json.loads(clean)
        except Exception as e:
            logger.warning(f"Erreur scoring wallet : {e}")
            return {"score_estimate": 0, "tier": "unknown", "strengths": [], "weaknesses": [], "recommended_actions": []}
