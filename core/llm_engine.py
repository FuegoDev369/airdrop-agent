"""
llm_engine.py — v1.2
Interface unifiée LLM — switch Groq (cloud) / Ollama (local)

CHANGELOG v1.2 :
  - Délai configurable entre appels (request_delay_seconds)
    pour réduire les 429 Too Many Requests sur le plan gratuit Groq
  - generate_tweet() forcé en anglais
  - generate_daily_brief() et notify messages en langue configurable
"""

import os
import time
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class LLMEngine:
    def __init__(self, config: dict):
        self.mode = config["llm"]["mode"]
        self.cfg = config["llm"][self.mode]
        self._client = None

        # Délai entre appels — réduit les 429 sur plan gratuit Groq
        self.request_delay = self.cfg.get("request_delay_seconds", 0.5)

        # Langue des outputs (hors tweets)
        lang_cfg = config.get("language", {})
        self.notification_language = lang_cfg.get("notification_language", "en")

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
            raise ImportError("Package 'requests' manquant.")

    def call(self, prompt: str, system: str = "") -> str:
        """Appel LLM unifié avec délai anti-429."""
        if self.request_delay > 0:
            time.sleep(self.request_delay)
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
        Toujours en anglais en interne (JSON structuré).
        """
        system = (
            "You are an expert Web3 analyst specializing in airdrops. "
            "You analyze signals (tweets, Discord/Telegram messages) for an airdrop tracker. "
            "Reply ONLY with valid JSON, no markdown, no explanation."
        )

        # Le résumé et l'action sont générés dans la langue de notification
        lang_note = (
            "Write 'summary' and 'action_required' in French."
            if self.notification_language == "fr"
            else f"Write 'summary' and 'action_required' in English."
        )

        prompt = f"""Analyze this signal for project "{project_name}":

CONTENT: {content[:1500]}

{lang_note}

Return exactly this JSON:
{{
  "signal_type": "quest|snapshot|tge_signal|major_announcement|regular_update|hype|irrelevant",
  "urgency_score": <integer 1-10>,
  "summary": "<1 sentence summary in the configured language>",
  "action_required": "<concrete action to take or null>",
  "keywords": ["<keyword1>", "<keyword2>"]
}}

Urgency scoring:
- 9-10: imminent snapshot, TGE announced, quest expiring < 24h
- 7-8 : new quest, major announcement, new testnet
- 5-6 : important update, partnership
- 3-4 : regular update, informational content
- 1-2 : general hype, noise, irrelevant"""

        try:
            response = self.call(prompt, system)
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

    def generate_tweet(self, project_name: str, context: str, language: str = "en") -> str:
        """
        Génère un tweet authentique et engagé.
        TOUJOURS en anglais — langue de la crypto sur Twitter/X.
        Le paramètre language est accepté mais ignoré (toujours "en").
        """
        # Forcé anglais — indépendant de la config notification_language
        system = (
            "You are a genuine Web3 community member passionate about crypto projects. "
            "You write authentic English tweets, never generic. "
            "Your tweets show real understanding of the project. "
            "NEVER use spam hashtags. Maximum 2 relevant hashtags. "
            "Reply only with the tweet text, no quotes."
        )

        prompt = f"""Write an engaging tweet for the project "{project_name}".

Recent project context:
{context[:800]}

Constraints:
- Maximum 260 characters
- Authentic tone, not corporate
- Shows real knowledge of the project
- Can include a question to engage the community
- 1-2 maximum relevant hashtags
- ALWAYS in English"""

        return self.call(prompt, system)

    def generate_daily_brief(self, projects_data: list) -> str:
        """Génère un briefing quotidien dans la langue configurée."""
        lang = self.notification_language
        lang_instruction = "in French" if lang == "fr" else "in English"

        system = (
            f"You are the assistant of a serious airdrop farmer. "
            f"Generate clear, actionable, prioritized briefings {lang_instruction}. "
            f"Be direct and concise."
        )

        projects_summary = json.dumps(projects_data, ensure_ascii=False, indent=2)

        prompt = f"""Generate a daily briefing based on this project data:

{projects_summary[:2000]}

Structure your briefing as:
1. 🔴 URGENT (actions < 24h)
2. 🟡 TODAY (recommended actions)
3. 🟢 WATCH (nothing urgent)
4. 💡 TIP OF THE DAY (1 strategic tip)

Be concise and actionable. Write {lang_instruction}."""

        return self.call(prompt, system)

    def score_wallet_eligibility(self, project_name: str, wallet_activity: dict) -> dict:
        """Estime le score d'éligibilité d'un wallet pour un airdrop."""
        system = (
            "You are an expert in tokenomics and airdrop eligibility criteria. "
            "Analyze wallet activity and estimate its position in a distribution. "
            "Reply in JSON only."
        )

        prompt = f"""Estimate eligibility for "{project_name}" airdrop:

Wallet activity: {json.dumps(wallet_activity, ensure_ascii=False)}

Return:
{{
  "score_estimate": <0-100>,
  "tier": "top_1pct|top_5pct|top_20pct|eligible|low|unknown",
  "strengths": ["<strength>"],
  "weaknesses": ["<weakness>"],
  "recommended_actions": ["<action to improve>"]
}}"""

        try:
            response = self.call(prompt, system)
            clean = response.strip().strip("```json").strip("```").strip()
            return json.loads(clean)
        except Exception as e:
            logger.warning(f"Erreur scoring wallet : {e}")
            return {
                "score_estimate": 0,
                "tier": "unknown",
                "strengths": [],
                "weaknesses": [],
                "recommended_actions": []
            }
