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

    except tweepy.Forbidden as e:
        # DM access requires Basic ($100/mo) or higher X API plan — skip silently
        logger.debug(f"[X] DM access not available on current API plan: {e}")
        return [], since_id
    except tweepy.Unauthorized as e:
        logger.debug(f"[X] DM unauthorized (check access token scopes): {e}")
        return [], since_id
    except Exception as e:
        logger.warning(f"[X] Error checking DMs: {e}")
        return [], since_id


def get_my_tweets(
    api_key: str, api_secret: str, bearer_token: str,
    access_token: str, access_token_secret: str,
    count: int = 5,
) -> str:
    """
    Returns Diego's most recent tweets with engagement metrics.
    count: how many tweets to retrieve (max 10).
    """
    client = build_client(api_key, api_secret, bearer_token, access_token, access_token_secret)
    user_id = get_user_id(client)
    if not user_id:
        return "No pude obtener el ID de usuario de @DiegoCapital_99."

    try:
        resp = client.get_users_tweets(
            user_id,
            max_results=min(count, 10),
            tweet_fields=["public_metrics", "text", "created_at"],
            exclude=["retweets"],
        )
        if not resp.data:
            return "No encontré tweets recientes en @DiegoCapital_99."

        lines = [f"Últimos {len(resp.data)} tweets de @DiegoCapital_99:\n"]
        for i, tweet in enumerate(resp.data, 1):
            pm = tweet.public_metrics or {}
            date_str = tweet.created_at.strftime("%d/%m/%Y %H:%M") if tweet.created_at else "?"
            lines.append(
                f"{i}. [{date_str}]\n"
                f"   {tweet.text[:200]}\n"
                f"   ❤️ {pm.get('like_count', 0)} likes · "
                f"🔁 {pm.get('retweet_count', 0)} RTs · "
                f"💬 {pm.get('reply_count', 0)} replies · "
                f"👁 {pm.get('impression_count', '?')} vistas\n"
            )
        return "\n".join(lines)

    except Exception as e:
        logger.warning(f"[X] Error fetching own tweets: {e}")
        return f"Error al consultar tus tweets: {e}"


def get_my_mentions(
    api_key: str, api_secret: str, bearer_token: str,
    access_token: str, access_token_secret: str,
    count: int = 10,
) -> str:
    """
    Returns Diego's most recent mentions on X.
    count: how many mentions to retrieve (max 10).
    """
    client = build_client(api_key, api_secret, bearer_token, access_token, access_token_secret)
    user_id = get_user_id(client)
    if not user_id:
        return "No pude obtener el ID de usuario de @DiegoCapital_99."

    try:
        resp = client.get_users_mentions(
            user_id,
            max_results=min(count, 10),
            tweet_fields=["created_at", "text", "public_metrics"],
            expansions=["author_id"],
            user_fields=["username", "name"],
        )

        users_by_id: dict = {}
        if resp.includes and resp.includes.get("users"):
            for u in resp.includes["users"]:
                users_by_id[str(u.id)] = u

        if not resp.data:
            return "No hay menciones recientes en @DiegoCapital_99."

        lines = [f"Últimas {len(resp.data)} menciones de @DiegoCapital_99:\n"]
        for i, tweet in enumerate(resp.data, 1):
            author = users_by_id.get(str(tweet.author_id))
            author_str = f"@{author.username} ({author.name})" if author else f"(id {tweet.author_id})"
            date_str = tweet.created_at.strftime("%d/%m/%Y %H:%M") if tweet.created_at else "?"
            pm = tweet.public_metrics or {}
            lines.append(
                f"{i}. {author_str} [{date_str}]\n"
                f"   {tweet.text[:200]}\n"
                f"   ❤️ {pm.get('like_count', 0)} · 🔁 {pm.get('retweet_count', 0)}\n"
            )
        return "\n".join(lines)

    except Exception as e:
        logger.warning(f"[X] Error fetching mentions: {e}")
        return f"Error al consultar menciones: {e}"


def post_tweet(
    api_key: str, api_secret: str, bearer_token: str,
    access_token: str, access_token_secret: str,
    text: str,
    video_bytes: bytes | None = None,
    video_filename: str = "video.mp4",
    poll_options: list[str] | None = None,
    poll_duration_hours: int = 24,
) -> str:
    """
    Posts a tweet, optionally with a video attachment or a native X poll.
    poll_options: list of 2–4 option strings (mutually exclusive with video).
    poll_duration_hours: how long the poll runs (1–168 hours, default 24).
    Returns a success or error string.
    """
    import tweepy.auth
    import requests as req_lib
    import time

    client = build_client(api_key, api_secret, bearer_token, access_token, access_token_secret)

    media_id = None
    if video_bytes:
        # Use v1.1 chunked upload for video
        auth = tweepy.OAuth1UserHandler(api_key, api_secret, access_token, access_token_secret)
        upload_url = "https://upload.twitter.com/1.1/media/upload.json"
        headers = {}
        auth_session = req_lib.Session()
        auth_session.auth = auth

        # INIT
        init_resp = auth_session.post(upload_url, data={
            "command": "INIT",
            "media_type": "video/mp4",
            "total_bytes": len(video_bytes),
            "media_category": "tweet_video",
        })
        if init_resp.status_code not in (200, 201, 202):
            return f"Error al inicializar la subida del video: {init_resp.text}"
        media_id = init_resp.json()["media_id_string"]

        # APPEND (in 5 MB chunks)
        chunk_size = 5 * 1024 * 1024
        for i, offset in enumerate(range(0, len(video_bytes), chunk_size)):
            chunk = video_bytes[offset: offset + chunk_size]
            append_resp = auth_session.post(upload_url, data={
                "command": "APPEND",
                "media_id": media_id,
                "segment_index": i,
            }, files={"media": chunk})
            if append_resp.status_code not in (200, 201, 202, 204):
                return f"Error al subir el video (segmento {i}): {append_resp.text}"

        # FINALIZE
        fin_resp = auth_session.post(upload_url, data={
            "command": "FINALIZE",
            "media_id": media_id,
        })
        if fin_resp.status_code not in (200, 201, 202):
            return f"Error al finalizar la subida del video: {fin_resp.text}"

        # Wait for processing
        processing_info = fin_resp.json().get("processing_info")
        while processing_info and processing_info.get("state") in ("pending", "in_progress"):
            wait = processing_info.get("check_after_secs", 3)
            time.sleep(wait)
            status_resp = auth_session.get(upload_url, params={
                "command": "STATUS", "media_id": media_id
            })
            processing_info = status_resp.json().get("processing_info", {})
            if processing_info.get("state") == "failed":
                return f"Error al procesar el video: {processing_info}"

        logger.info(f"[X] Video uploaded successfully, media_id={media_id}")

    # Post tweet
    try:
        kwargs: dict = {"text": text}
        if media_id:
            kwargs["media_ids"] = [media_id]
        if poll_options:
            if len(poll_options) < 2 or len(poll_options) > 4:
                return "Error: una encuesta requiere entre 2 y 4 opciones."
            duration_minutes = max(5, min(poll_duration_hours * 60, 10080))  # clamp 5 min – 7 days
            kwargs["poll_options"] = poll_options
            kwargs["poll_duration_minutes"] = duration_minutes
        resp = client.create_tweet(**kwargs)
        tweet_id = resp.data["id"]
        kind = "Encuesta" if poll_options else "Tweet"
        logger.info(f"[X] {kind} posted: {tweet_id}")
        return f"✓ {kind} publicado exitosamente (id: {tweet_id})"
    except Exception as e:
        logger.error(f"[X] Error posting tweet: {e}")
        return f"Error al publicar el tweet: {e}"


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
