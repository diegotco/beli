"""
tools/web_tool.py - Web browsing, search, and form interaction for Beli via Firecrawl.

Firecrawl converts any URL into clean markdown, can search the web,
and can interact with pages (click, fill forms, submit).
API docs: https://docs.firecrawl.dev
"""
import logging

logger = logging.getLogger("beli.tools.web")

_MAX_CONTENT_CHARS = 8000  # Trim long pages to avoid flooding the context


def web_scrape(api_key: str, url: str) -> str:
    """
    Fetches a URL and returns its content as clean markdown.
    Use this when the owner shares a link and wants to know what's on it.
    """
    if not api_key:
        return "No está configurada la API key de Firecrawl (FIRECRAWL_API_KEY)."
    try:
        from firecrawl import FirecrawlApp
        app = FirecrawlApp(api_key=api_key)
        result = app.scrape_url(url, formats=["markdown"])
        content = result.markdown or ""
        if not content.strip():
            return f"No pude extraer contenido de {url}. La página puede requerir JavaScript o estar bloqueada."
        if len(content) > _MAX_CONTENT_CHARS:
            content = content[:_MAX_CONTENT_CHARS] + f"\n\n[...contenido recortado — {len(content)} caracteres en total]"
        title = getattr(result, "metadata", {}) and result.metadata.get("title", "")
        header = f"**{title}**\n{url}\n\n" if title else f"{url}\n\n"
        return header + content
    except Exception as e:
        logger.exception(f"[Firecrawl] Error scraping {url}: {e}")
        return f"Error al acceder a {url}: {e}"


def web_search(api_key: str, query: str, limit: int = 5) -> str:
    """
    Searches the web for a query and returns a summary of the top results.
    Use this when the owner asks about current events, news, prices, or anything external.
    """
    if not api_key:
        return "No está configurada la API key de Firecrawl (FIRECRAWL_API_KEY)."
    try:
        from firecrawl import FirecrawlApp
        app = FirecrawlApp(api_key=api_key)
        results = app.search(query, limit=limit)
        if not results:
            return f"No encontré resultados para: {query}"

        lines = [f"Resultados de búsqueda para: **{query}**\n"]
        for i, r in enumerate(results, 1):
            title   = r.get("title", "Sin título") if isinstance(r, dict) else getattr(r, "title", "Sin título")
            url     = r.get("url", "")             if isinstance(r, dict) else getattr(r, "url", "")
            snippet = r.get("description", "")     if isinstance(r, dict) else getattr(r, "description", "")
            lines.append(f"{i}. **{title}**")
            if url:
                lines.append(f"   {url}")
            if snippet:
                lines.append(f"   {snippet[:300]}")
            lines.append("")

        return "\n".join(lines).strip()
    except Exception as e:
        logger.exception(f"[Firecrawl] Error searching '{query}': {e}")
        return f"Error al buscar '{query}': {e}"


def web_api_call(
    method: str,
    url: str,
    body: dict | None = None,
    headers: dict | None = None,
    bearer_token: str | None = None,
) -> str:
    """
    Makes an HTTP request to any REST API and returns the JSON response.
    Use this to call external APIs — register agent accounts, post data, etc.
    """
    import requests as req
    import json

    h = {"Content-Type": "application/json"}
    if headers:
        h.update(headers)
    if bearer_token:
        h["Authorization"] = f"Bearer {bearer_token}"

    try:
        resp = req.request(
            method=method.upper(),
            url=url,
            json=body,
            headers=h,
            timeout=15,
        )
        try:
            data = resp.json()
            result = json.dumps(data, ensure_ascii=False, indent=2)
        except Exception:
            result = resp.text

        status = resp.status_code
        logger.info(f"[web_api_call] {method.upper()} {url} → {status}")
        if not resp.ok:
            return f"Error {status}:\n{result}"
        return f"✓ {status}\n\n{result}"
    except Exception as e:
        logger.exception(f"[web_api_call] Error calling {url}: {e}")
        return f"Error al llamar {url}: {e}"


def web_fill_form(api_key: str, url: str, actions: list) -> str:
    """
    Interacts with a webpage: fills form fields, clicks buttons, submits forms.

    actions is a list of dicts, each with:
      {"type": "click",      "selector": "css-selector"}
      {"type": "write",      "selector": "css-selector", "text": "value"}
      {"type": "wait",       "milliseconds": 1000}
      {"type": "screenshot"}  (returns visual confirmation)

    Returns the final page content after all actions are performed.
    Use this to register accounts, fill forms, or interact with web apps.
    """
    if not api_key:
        return "No está configurada la API key de Firecrawl (FIRECRAWL_API_KEY)."
    try:
        from firecrawl import FirecrawlApp
        app = FirecrawlApp(api_key=api_key)
        result = app.scrape_url(
            url,
            formats=["markdown"],
            actions=actions,
        )
        content = result.markdown or ""
        if not content.strip():
            return "Las acciones se ejecutaron pero la página resultante está vacía o bloqueada."
        if len(content) > _MAX_CONTENT_CHARS:
            content = content[:_MAX_CONTENT_CHARS] + f"\n\n[...contenido recortado]"
        logger.info(f"[Firecrawl] web_fill_form on {url} — {len(actions)} actions, result length: {len(content)}")
        return content
    except Exception as e:
        logger.exception(f"[Firecrawl] Error filling form on {url}: {e}")
        return f"Error al interactuar con {url}: {e}"
