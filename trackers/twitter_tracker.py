"""
twitter_tracker.py
Scraping Twitter via instances Nitter publiques — sans API key.
Fallback automatique si une instance est hors-ligne.
"""

import re
import time
import logging
import requests
from datetime import datetime
from typing import Optional
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class TwitterTracker:
    def __init__(self, config: dict):
        self.cfg = config.get("twitter", {})
        self.instances = self.cfg.get("nitter_instances", [
            "https://nitter.net",
            "https://nitter.privacydev.net",
            "https://nitter.poast.org",
            "https://nitter.1d4.us",
        ])
        self.tweets_per_project = self.cfg.get("tweets_per_project", 15)
        self.delay = self.cfg.get("request_delay_seconds", 2)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36",
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
        })

    def _try_instance(self, instance: str, handle: str) -> Optional[list]:
        """Tente de récupérer les tweets depuis une instance Nitter."""
        url = f"{instance}/{handle}"
        try:
            resp = self.session.get(url, timeout=15)
            if resp.status_code != 200:
                return None

            soup = BeautifulSoup(resp.text, "html.parser")
            tweet_items = soup.find_all("div", class_="timeline-item")

            if not tweet_items:
                return None

            tweets = []
            for item in tweet_items[:self.tweets_per_project]:
                try:
                    # Texte du tweet
                    content_el = item.find("div", class_="tweet-content")
                    if not content_el:
                        continue
                    content = content_el.get_text(separator=" ", strip=True)

                    # Date
                    date_el = item.find("span", class_="tweet-date")
                    date_str = ""
                    if date_el and date_el.find("a"):
                        date_str = date_el.find("a").get("title", "")

                    # Stats
                    stats = {}
                    for stat in item.find_all("span", class_="icon-container"):
                        parent = stat.parent
                        if parent:
                            text = parent.get_text(strip=True)
                            if "retweet" in str(stat).lower():
                                stats["retweets"] = self._parse_count(text)
                            elif "like" in str(stat).lower() or "heart" in str(stat).lower():
                                stats["likes"] = self._parse_count(text)

                    # URL du tweet original
                    link_el = item.find("a", class_="tweet-link")
                    tweet_url = ""
                    if link_el:
                        href = link_el.get("href", "")
                        tweet_url = f"https://twitter.com{href}" if href.startswith("/") else href

                    tweets.append({
                        "content": content,
                        "date": date_str,
                        "url": tweet_url,
                        "stats": stats,
                        "source": "twitter",
                    })
                except Exception as e:
                    logger.debug(f"Erreur parsing tweet : {e}")
                    continue

            return tweets if tweets else None

        except requests.RequestException as e:
            logger.debug(f"Instance {instance} indisponible : {e}")
            return None

    def _parse_count(self, text: str) -> int:
        """Parse des compteurs comme '1.2K', '3.4M'."""
        text = text.strip().upper()
        try:
            if "K" in text:
                return int(float(text.replace("K", "")) * 1000)
            if "M" in text:
                return int(float(text.replace("M", "")) * 1000000)
            return int(re.sub(r"[^0-9]", "", text) or 0)
        except ValueError:
            return 0

    def get_tweets(self, handle: str) -> list:
        """
        Récupère les tweets d'un compte avec fallback automatique entre instances.
        Retourne une liste de dicts tweets.
        """
        if not handle:
            return []

        for i, instance in enumerate(self.instances):
            logger.debug(f"Tentative instance {i+1}/{len(self.instances)} : {instance}")
            tweets = self._try_instance(instance, handle)
            if tweets is not None:
                logger.info(f"@{handle} : {len(tweets)} tweets récupérés via {instance}")
                time.sleep(self.delay)
                return tweets
            time.sleep(1)

        logger.warning(f"@{handle} : toutes les instances Nitter ont échoué")
        return []

    def check_snapshot_signals(self, tweets: list) -> bool:
        """Détecte des mots-clés associés à un snapshot imminent."""
        SNAPSHOT_KEYWORDS = [
            "snapshot", "eligible", "eligib", "airdrop", "tge", "token launch",
            "claim", "distribution", "genesis", "mainnet launch", "go live",
            "criteria", "cutoff", "deadline", "last chance", "ends soon",
        ]
        combined = " ".join(t["content"].lower() for t in tweets)
        return any(kw in combined for kw in SNAPSHOT_KEYWORDS)

    def check_quest_signals(self, tweets: list) -> list:
        """Détecte des annonces de quêtes dans les tweets."""
        QUEST_KEYWORDS = [
            "quest", "mission", "task", "challenge", "bounty",
            "zealy", "galxe", "guild", "earn", "role", "points",
            "compete", "leaderboard", "reward", "testnet",
        ]
        found = []
        for tweet in tweets:
            content_lower = tweet["content"].lower()
            if any(kw in content_lower for kw in QUEST_KEYWORDS):
                found.append(tweet)
        return found
