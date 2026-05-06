"""
twitter_tracker.py — v1.9
Twitter scraping via public Nitter instances — no API key required.
Automatic fallback if an instance is offline.

CHANGELOG v1.9:
  - Full translation to English (comments, logs, docstrings)
  - No functional changes
"""

import re
import time
import logging
import requests
from typing import Optional
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class TwitterTracker:
    def __init__(self, config: dict):
        self.cfg              = config.get("twitter", {})
        self.instances        = self.cfg.get("nitter_instances", [
            "https://nitter.net",
            "https://nitter.privacydev.net",
            "https://nitter.poast.org",
            "https://nitter.1d4.us",
        ])
        self.tweets_per_project = self.cfg.get("tweets_per_project", 15)
        self.delay              = self.cfg.get("request_delay_seconds", 2)

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent":      "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        })

    def _try_instance(self, instance: str, handle: str) -> Optional[list]:
        """Attempt to fetch tweets from a single Nitter instance."""
        url = f"{instance}/{handle}"
        try:
            resp = self.session.get(url, timeout=15)
            if resp.status_code != 200:
                return None

            soup       = BeautifulSoup(resp.text, "html.parser")
            tweet_items = soup.find_all("div", class_="timeline-item")

            if not tweet_items:
                return None

            tweets = []
            for item in tweet_items[:self.tweets_per_project]:
                try:
                    content_el = item.find("div", class_="tweet-content")
                    if not content_el:
                        continue
                    content = content_el.get_text(separator=" ", strip=True)

                    date_el  = item.find("span", class_="tweet-date")
                    date_str = ""
                    if date_el and date_el.find("a"):
                        date_str = date_el.find("a").get("title", "")

                    stats = {}
                    for stat in item.find_all("span", class_="icon-container"):
                        parent = stat.parent
                        if parent:
                            text = parent.get_text(strip=True)
                            if "retweet" in str(stat).lower():
                                stats["retweets"] = self._parse_count(text)
                            elif "like" in str(stat).lower() or "heart" in str(stat).lower():
                                stats["likes"] = self._parse_count(text)

                    link_el   = item.find("a", class_="tweet-link")
                    tweet_url = ""
                    if link_el:
                        href      = link_el.get("href", "")
                        tweet_url = f"https://twitter.com{href}" if href.startswith("/") else href

                    tweets.append({
                        "content": content,
                        "date":    date_str,
                        "url":     tweet_url,
                        "stats":   stats,
                        "source":  "twitter",
                    })
                except Exception as e:
                    logger.debug(f"Tweet parsing error: {e}")
                    continue

            return tweets if tweets else None

        except requests.RequestException as e:
            logger.debug(f"Instance {instance} unavailable: {e}")
            return None

    def _parse_count(self, text: str) -> int:
        """Parse counters like '1.2K', '3.4M'."""
        text = text.strip().upper()
        try:
            if "K" in text:
                return int(float(text.replace("K", "")) * 1000)
            if "M" in text:
                return int(float(text.replace("M", "")) * 1_000_000)
            return int(re.sub(r"[^0-9]", "", text) or 0)
        except ValueError:
            return 0

    def get_tweets(self, handle: str) -> list:
        """
        Fetch tweets for an account with automatic fallback between Nitter instances.
        Returns a list of tweet dicts.
        """
        if not handle:
            return []

        for i, instance in enumerate(self.instances):
            logger.debug(f"Trying instance {i + 1}/{len(self.instances)}: {instance}")
            tweets = self._try_instance(instance, handle)
            if tweets is not None:
                logger.info(f"@{handle}: {len(tweets)} tweets fetched via {instance}")
                time.sleep(self.delay)
                return tweets
            time.sleep(1)

        logger.warning(f"@{handle}: all Nitter instances failed")
        return []

    def check_snapshot_signals(self, tweets: list) -> bool:
        """Detect keywords associated with an imminent snapshot."""
        SNAPSHOT_KEYWORDS = [
            "snapshot", "eligible", "eligib", "airdrop", "tge", "token launch",
            "claim", "distribution", "genesis", "mainnet launch", "go live",
            "criteria", "cutoff", "deadline", "last chance", "ends soon",
        ]
        combined = " ".join(t["content"].lower() for t in tweets)
        return any(kw in combined for kw in SNAPSHOT_KEYWORDS)

    def check_quest_signals(self, tweets: list) -> list:
        """Detect quest announcements in tweets."""
        QUEST_KEYWORDS = [
            "quest", "mission", "task", "challenge", "bounty",
            "zealy", "galxe", "guild", "earn", "role", "points",
            "compete", "leaderboard", "reward", "testnet",
        ]
        return [
            tweet for tweet in tweets
            if any(kw in tweet["content"].lower() for kw in QUEST_KEYWORDS)
        ]
