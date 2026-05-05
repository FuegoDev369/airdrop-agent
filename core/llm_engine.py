"""
llm_engine.py — v1.5
Interface unifiée LLM — switch Groq (cloud) / Ollama (local)

CHANGELOG v1.5 :
  - classify_signals_batch() : classe N signaux en 1 seul appel LLM
    au lieu de N appels individuels → divise par ~15 les appels Groq
  - Plus de 429 possible quelle que soit la taille du projet
  - classify_signal() conservé comme fallback (1 signal à la fois)
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
        self.request_delay = self.cfg.get("request_delay_seconds", 1.5)

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

    # ── BATCH CLASSIFICATION — LE COEUR DU CHANGEMENT v1.5 ──

    def classify_signals_batch(self, contents: list[str], project_name: str) -> list[dict]:
        """
        Classifie N signaux en UN SEUL appel LLM.

        Avant (v1.4) : 15 tweets → 15 appels Groq → risque 429 + lent
        Après (v1.5) : 15 tweets → 1 appel Groq  → zéro 429 + rapide

        Args:
            contents: liste de textes bruts à classifier
            project_name: nom du projet pour le contexte

        Returns:
            liste de dicts avec signal_type, urgency_score, summary, action_required
            Dans le même ordre que contents. En cas d'erreur partielle,
            retourne un dict par défaut pour l'index concerné.
        """
        if not contents:
            return []

        lang_note = (
            "Write 'summary' and 'action_required' fields in French."
            if self.notification_language == "fr"
            else "Write 'summary' and 'action_required' fields in English."
        )

        # Formater les signaux numérotés pour le prompt
        numbered = "\n\n".join(
            f"[{i}] {c[:400]}" for i, c in enumerate(contents)
        )

        system = (
            "You are an expert Web3 analyst specializing in airdrops. "
            "You classify multiple signals at once for an airdrop tracker. "
            "Reply ONLY with a valid JSON array, no markdown, no explanation. "
            "The array must have exactly the same number of items as signals provided."
        )

        prompt = f"""Classify these {len(contents)} signals for project "{project_name}".

{lang_note}

SIGNALS:
{numbered}

Return a JSON array with exactly {len(contents)} objects, one per signal, in order:
[
  {{
    "index": 0,
    "signal_type": "quest|snapshot|tge_signal|major_announcement|regular_update|hype|irrelevant",
    "urgency_score": <integer 1-10>,
    "summary": "<1 sentence in configured language>",
    "action_required": "<concrete action or null>",
    "keywords": ["<kw1>", "<kw2>"]
  }},
  ...
]

Urgency scoring rules:
- 9-10: imminent snapshot, TGE announced, quest expiring < 24h
- 7-8 : new quest, major announcement, new testnet, hack/security alert
- 5-6 : important update, partnership announcement
- 3-4 : regular update, informational content
- 1-2 : general hype, noise, irrelevant"""

        try:
            response = self.call(prompt, system)
            clean = response.strip().strip("```json").strip("```").strip()
            results = json.loads(clean)

            # Validation : s'assurer qu'on a le bon nombre de résultats
            if not isinstance(results, list):
                raise ValueError("Réponse LLM n'est pas une liste JSON")

            # Normaliser et compléter si manquants
            normalized = []
            for i, content in enumerate(contents):
                # Chercher le résultat correspondant à cet index
                found = next(
                    (r for r in results if r.get("index") == i),
                    None
                )
                if found:
                    normalized.append({
                        "signal_type": found.get("signal_type", "regular_update"),
                        "urgency_score": int(found.get("urgency_score", 3)),
                        "summary": found.get("summary", content[:100]),
                        "action_required": found.get("action_required"),
                        "keywords": found.get("keywords", []),
                    })
                else:
                    # Fallback pour cet index si manquant dans la réponse
                    normalized.append(self._default_classification(content))

            logger.info(
                f"Batch classifié : {len(normalized)} signaux en 1 appel LLM "
                f"(projet: {project_name})"
            )
            return normalized

        except (json.JSONDecodeError, ValueError, Exception) as e:
            logger.warning(f"Erreur batch classification : {e} — fallback individuel")
            # Fallback : classifier individuellement si le batch échoue
            return [self._fallback_classify(c, project_name) for c in contents]

    def _default_classification(self, content: str) -> dict:
        """Classification par défaut quand un item manque dans la réponse batch."""
        return {
            "signal_type": "regular_update",
            "urgency_score": 3,
            "summary": content[:100],
            "action_required": None,
            "keywords": [],
        }

    def _fallback_classify(self, content: str, project_name: str) -> dict:
        """Fallback individuel si le batch entier échoue."""
        try:
            return self.classify_signal(content, project_name)
        except Exception:
            return self._default_classification(content)

    # ── Classification individuelle (fallback / compatibilité) ──

    def classify_signal(self, content: str, project_name: str) -> dict:
        """
        Classifie UN signal — conservé comme fallback.
        Préférer classify_signals_batch() pour les lots.
        """
        lang_note = (
            "Write 'summary' and 'action_required' in French."
            if self.notification_language == "fr"
            else "Write 'summary' and 'action_required' in English."
        )

        system = (
            "You are an expert Web3 analyst specializing in airdrops. "
            "Reply ONLY with valid JSON, no markdown, no explanation."
        )

        prompt = f"""Analyze this signal for project "{project_name}":

CONTENT: {content[:1500]}

{lang_note}

Return exactly this JSON:
{{
  "signal_type": "quest|snapshot|tge_signal|major_announcement|regular_update|hype|irrelevant",
  "urgency_score": <integer 1-10>,
  "summary": "<1 sentence summary>",
  "action_required": "<concrete action or null>",
  "keywords": ["<kw1>", "<kw2>"]
}}"""

        try:
            response = self.call(prompt, system)
            clean = response.strip().strip("```json").strip("```").strip()
            return json.loads(clean)
        except Exception as e:
            logger.warning(f"Erreur classification signal : {e}")
            return self._default_classification(content)

    # ── Génération tweet ─────────────────────────────────────

    def generate_tweet(self, project_name: str, context: str, language: str = "en") -> str:
        """Génère un tweet — TOUJOURS en anglais."""
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

    # ── Briefing quotidien ───────────────────────────────────

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

Structure:
1. 🔴 URGENT (actions < 24h)
2. 🟡 TODAY (recommended actions)
3. 🟢 WATCH (nothing urgent)
4. 💡 TIP OF THE DAY (1 strategic tip)

Write {lang_instruction}. Be concise and actionable."""

        return self.call(prompt, system)

    # ── Scoring wallet ───────────────────────────────────────

    def score_wallet_eligibility(self, project_name: str, wallet_activity: dict) -> dict:
        """Estime le score d'éligibilité d'un wallet pour un airdrop."""
        system = (
            "You are an expert in tokenomics and airdrop eligibility criteria. "
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
  "recommended_actions": ["<action>"]
}}"""

        try:
            response = self.call(prompt, system)
            clean = response.strip().strip("```json").strip("```").strip()
            return json.loads(clean)
        except Exception as e:
            logger.warning(f"Erreur scoring wallet : {e}")
            return {"score_estimate": 0, "tier": "unknown",
                    "strengths": [], "weaknesses": [], "recommended_actions": []}
