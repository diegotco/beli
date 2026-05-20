"""
tools/x_monitor.py - Monitors X (@DiegoCapital_99) for new mentions, likes, and DMs.

Polls the X API v2 every 15 minutes and sends Telegram notifications.
State (last seen IDs, like counts) is persisted in Beli's database via MemoryManager.

Credentials come from env vars (Railway only, never git):
  X_API_KEY, X_API_SECRET, X_BEARER_TOKEN, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET
"""
import json
import logging
import tweepy

logger = logging.getLogger("beli.x_monitor")

_USERNAME = "DiegoCapital_99"


def build_client(api_key: str, api_secret: str, bearer_token: str,
                 access_token: str, access_token_secret: str) -> tweepy.Client:
    return tweepy.Client(
        bearer_token=bearer_token,
        consumer_key=api_key,
        consumer_secret=api_secret,
        access_token=access_token,
        access_token_secret=access_token_secret,
        wait_on_rate_limit=False,
    )


def get_user_id(client: tweepy.Client, username: str = _USERNAME) -> str | None:
    try:
        resp = client.get_user(username=username)
        if resp.data:
            return str(resp.data.id)
    except Exception as e:
        logger.warning(f"[X] Could not resolve user ID for @{username}: {e}")
    return None


def check_new_mentions(client: tweepy.Client, user_id: str,
                       since_id: str | None = None) -> tuple[list[dict], str | None]:
    """Returns (new_mentions, latest_id). Each mention has id, text, author_id."""
    try:
        kwargs: dict = {"tweet_fields": ["created_at", "text"],
                        "expansions": ["author_id"],
                        "user_fields": ["username", "name"]}
        if since_id:
            kwargs["since_id"] = since_id

        resp = client.get_users_mentions(user_id, **kwargs)
        mentions = []
        latest_id = since_id

        users_by_id = {}
        if resp.includes and resp.includes.get("users"):
            for u in resp.includes["users"]:
                users_by_id[str(u.id)] = u

        if resp.data:
            for tweet in resp.data:
                author = users_by_id.get(str(tweet.author_id))
                author_str = f"@{author.username}" if author else f"(id {tweet.author_id})"
                mentions.append({"id": str(tweet.id), "text": tweet.text, "author": author_str})
                if latest_id is None or int(tweet.id) > int(latest_id):
                    latest_id = str(tweet.id)

        return mentions, latest_id

    except Exception as e:
        logger.warning(f"[X] Error checking mentions: {e}")
        return [], since_id


def check_like_changes(client: tweepy.Client, user_id: str,
                       cached_counts: dict | None = None) -> tuple[list[dict], dict]:
    """
    Returns (changes, new_counts).
    Changes is a list of tweets whose like count increased since last check.
    """
    if cached_counts is None:
        cached_counts = {}

    try:
        resp = client.get_users_tweets(
            user_id,
            max_results=10,
            tweet_fields=["public_metrics", "text"],
            exclude=["retweets"],
        )

        new_counts: dict = {}
        changes: list[dict] = []

        if resp.data:
            for tweet in resp.data:
                tid = str(tweet.id)
                current = tweet.public_metrics.get("like_count", 0) if tweet.public_metrics else 0
                new_counts[tid] = current

                if tid in cached_counts:
                    delta = current - cached_counts[tid]
                    if delta > 0:
                        changes.append({
                            "tweet_id": tid,
                            "text": tweet.text[:120],
                            "new_likes": delta,
                            "total_likes": current,
                        })

        # Keep cached counts for tweets no longer in the last 10
        merged = {**cached_counts, **new_counts}
        # Only keep IDs still in the latest batch to avoid unbounded growth
        final_counts = {k: v for k, v in merged.items() if k in new_counts}
        return changes, final_counts

    except Exception as e:
        logger.warning(f"[X] Error checking likes: {e}")
        return [], cached_counts


def check_new_dms(client: tweepy.Client,
                  since_id: str | None = None) -> tuple[list[dict], str | None]:
    """Returns (new_dms, latest_id). Each DM has id, text, sender_id."""
    try:
        kwargs: dict = {"dm_event_fields": ["created_at", "text", "sender_id"],
                        "expansions": ["sender_id"],
                        "user_fields": ["username", "name"]}
        if since_id:
            kwargs["since_id"] = since_id

        resp = client.get_dm_events(**kwargs)
        dms = []
        latest_id = since_id

        users_by_id = {}
        if resp.includes and resp.includes.get("users"):
            for u in resp.includes["users"]:
                users_by_id[str(u.id)] = u

        if resp.data:
            for event in resp.data:
                if getattr(event, "event_type", "") == "MessageCreate":
                    sender = users_by_id.get(str(event.sender_id))
                    sender_str = f"@{sender.username}" if sender else f"(id {event.sender_id})"
                    dms.append({"id": str(event.id), "text": event.text, "sender": sender_str})
                    if latest_id is None or int(event.id) > int(latest_id):
                        latest_id = str(event.id)

        return dms, latest_id

    except Exception as e:
        logger.warning(f"[X] Error checking DMs: {e}")
        return [], since_id


def format_notifications(mentions: list[dict], like_changes: list[dict],
                         dms: list[dict]) -> list[str]:
    """Formats activity into Telegram-ready strings."""
    messages = []

    for m in mentions:
        messages.append(
            f"🔔 Nueva mencion en X\n"
            f"{m['author']}: {m['text'][:280]}"
        )

    for lc in like_changes:
        noun = "like" if lc["new_likes"] == 1 else "likes"
        messages.append(
            f"❤️ +{lc['new_likes']} {noun} en tu tweet ({lc['total_likes']} total)\n"
            f"{lc['text']}"
        )

    for dm in dms:
        messages.append(
            f"💬 Nuevo DM en X de {dm['sender']}\n"
            f"{dm['text'][:280]}"
        )

    return messages
