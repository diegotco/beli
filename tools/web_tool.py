"""
tools/web_tool.py - Web browsing and search for Beli via Firecrawl.

Firecrawl converts any URL into clean markdown and can search the web.
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
        # Trim if too long
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
    Use this when the owner asks about something that requires current or external information.
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
            title   = getattr(r, "title", "") or r.get("title", "") if isinstance(r, dict) else getattr(r, "title", "Sin título")
            url     = getattr(r, "url", "")   or r.get("url", "")   if isinstance(r, dict) else getattr(r, "url", "")
            snippet = getattr(r, "description", "") or r.get("description", "") if isinstance(r, dict) else getattr(r, "description", "")
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
