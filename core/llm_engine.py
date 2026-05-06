"""
llm_engine.py — v1.9
Unified LLM interface — switches between Groq (cloud) and Ollama (local)
based on configuration in settings.yaml.

CHANGELOG v1.9:
  - Full translation to English (comments, logs, docstrings, prompts)
  - Notification language still configurable (notification_language setting)
  - Tweet generation always in English (hardcoded — crypto standard)
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
        self.cfg  = config["llm"][self.mode]
        self._client      = None
        self.request_delay = self.cfg.get("request_delay_seconds", 1.5)

        lang_cfg = config.get("language", {})
        self.notification_language = lang_cfg.get("notification_language", "en")

        logger.info(f"LLM Engine initialized — mode: {self.mode}")

    # ── Backend clients ──────────────────────────────────────

    def _get_groq_client(self):
        if self._client is None:
            try:
                from groq import Groq
                api_key = os.environ.get("GROQ_API_KEY")
                if not api_key:
                    raise ValueError("GROQ_API_KEY missing from environment variables")
                self._client = Groq(api_key=api_key)
            except ImportError:
                raise ImportError("Package 'groq' missing. Run: pip install groq")
        return self._client

    def _call_groq(self, prompt: str, system: str = "") -> str:
        client   = self._get_groq_client()
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
                "model":  self.cfg["model"],
                "prompt": prompt,
                "system": system,
                "stream": False,
                "options": {
                    "temperature":  self.cfg["temperature"],
                    "num_predict":  self.cfg["max_tokens"],
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
            raise ImportError("Package 'requests' missing.")

    def call(self, prompt: str, system: str = "") -> str:
        """Unified LLM call with configurable delay to prevent rate limiting."""
        if self.request_delay > 0:
            time.sleep(self.request_delay)
        try:
            if self.mode == "groq":
                return self._call_groq(prompt, system)
            elif self.mode == "ollama":
                return self._call_ollama(prompt, system)
            else:
                raise ValueError(f"Unknown LLM mode: {self.mode}")
        except Exception as e:
            logger.error(f"LLM error ({self.mode}): {e}")
            raise

    # ── Batch classification — core of v1.5 optimization ────

    def classify_signals_batch(self, contents: list, project_name: str) -> list:
        """
        Classify N signals in a SINGLE LLM call.

        Before (v1.4): 15 tweets → 15 Groq calls → risk of 429 + slow
        After  (v1.5): 15 tweets → 1 Groq call  → no 429 + fast

        Args:
            contents     : list of raw text strings to classify
            project_name : project name for context

        Returns:
            list of dicts in the same order as contents.
            Falls back to individual classification if batch fails.
        """
        if not contents:
            return []

        lang_note = (
            "Write 'summary' and 'action_required' fields in French."
            if self.notification_language == "fr"
            else "Write 'summary' and 'action_required' fields in English."
        )

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
    "action_required": "<concrete action to take or null>",
    "keywords": ["<kw1>", "<kw2>"]
  }},
  ...
]

Urgency scoring:
- 9-10: imminent snapshot, TGE announced, quest expiring < 24h, security incident
- 7-8 : new quest, major announcement, new testnet phase, hack/exploit detected
- 5-6 : important update, partnership announcement, roadmap update
- 3-4 : regular update, informational content, community post
- 1-2 : general hype, noise, off-topic, irrelevant"""

        try:
            response = self.call(prompt, system)
            clean    = response.strip().strip("```json").strip("```").strip()
            results  = json.loads(clean)

            if not isinstance(results, list):
                raise ValueError("LLM response is not a JSON array")

            normalized = []
            for i, content in enumerate(contents):
                found = next((r for r in results if r.get("index") == i), None)
                if found:
                    normalized.append({
                        "signal_type":     found.get("signal_type", "regular_update"),
                        "urgency_score":   int(found.get("urgency_score", 3)),
                        "summary":         found.get("summary", content[:100]),
                        "action_required": found.get("action_required"),
                        "keywords":        found.get("keywords", []),
                    })
                else:
                    normalized.append(self._default_classification(content))

            logger.info(
                f"Batch classified: {len(normalized)} signals in 1 LLM call "
                f"(project: {project_name})"
            )
            return normalized

        except (json.JSONDecodeError, ValueError, Exception) as e:
            logger.warning(f"Batch classification error: {e} — falling back to individual")
            return [self._fallback_classify(c, project_name) for c in contents]

    def _default_classification(self, content: str) -> dict:
        """Default classification when an item is missing from batch response."""
        return {
            "signal_type":     "regular_update",
            "urgency_score":   3,
            "summary":         content[:100],
            "action_required": None,
            "keywords":        [],
        }

    def _fallback_classify(self, content: str, project_name: str) -> dict:
        """Individual fallback if the entire batch fails."""
        try:
            return self.classify_signal(content, project_name)
        except Exception:
            return self._default_classification(content)

    # ── Individual classification (fallback / compatibility) ─

    def classify_signal(self, content: str, project_name: str) -> dict:
        """Classify a single signal. Prefer classify_signals_batch() for batches."""
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
            clean    = response.strip().strip("```json").strip("```").strip()
            return json.loads(clean)
        except Exception as e:
            logger.warning(f"Signal classification error: {e}")
            return self._default_classification(content)

    # ── Tweet generation ─────────────────────────────────────

    def generate_tweet(self, project_name: str, context: str, language: str = "en") -> str:
        """
        Generate an authentic engagement tweet.
        ALWAYS in English — the standard language of crypto on Twitter/X.
        The language parameter is accepted but ignored.
        """
        system = (
            "You are a genuine Web3 community member passionate about crypto projects. "
            "You write authentic English tweets, never generic or corporate. "
            "Your tweets demonstrate real knowledge of the project. "
            "NEVER use spam hashtags. Maximum 2 relevant hashtags. "
            "Reply only with the tweet text, no quotes, no explanation."
        )

        prompt = f"""Write an engaging tweet for the project "{project_name}".

Recent project context:
{context[:800]}

Requirements:
- Maximum 260 characters
- Authentic, conversational tone
- Shows real understanding of the project
- May include a question to engage the community
- 1-2 relevant hashtags maximum
- ALWAYS in English"""

        return self.call(prompt, system)

    # ── Daily briefing ───────────────────────────────────────

    def generate_daily_brief(self, projects_data: list) -> str:
        """Generate a daily briefing in the configured notification language."""
        lang             = self.notification_language
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
1. 🔴 URGENT (actions required < 24h)
2. 🟡 TODAY (recommended actions)
3. 🟢 WATCH (nothing urgent)
4. 💡 TIP OF THE DAY (1 strategic insight)

Write {lang_instruction}. Be concise and actionable."""

        return self.call(prompt, system)

    # ── Wallet eligibility scoring ───────────────────────────

    def score_wallet_eligibility(self, project_name: str, wallet_activity: dict) -> dict:
        """Estimate wallet eligibility score for an airdrop."""
        system = (
            "You are an expert in tokenomics and airdrop eligibility criteria. "
            "Analyze wallet activity and estimate its probable position in a distribution. "
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
  "recommended_actions": ["<action to improve eligibility>"]
}}"""

        try:
            response = self.call(prompt, system)
            clean    = response.strip().strip("```json").strip("```").strip()
            return json.loads(clean)
        except Exception as e:
            logger.warning(f"Wallet scoring error: {e}")
            return {
                "score_estimate":      0,
                "tier":                "unknown",
                "strengths":           [],
                "weaknesses":          [],
                "recommended_actions": [],
            }
