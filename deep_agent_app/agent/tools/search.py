"""Company-independent internet search tool."""

from typing import Literal

import httpx

from markdownify import markdownify

from tavily import AsyncTavilyClient

from deep_agent_app.utilities.constants import TAVILY_API_KEY

_client = None
_web_client = None


async def fetch_webpage_content(url: str, timeout: float = 30.0) -> str:
    """Fetch and convert webpage content to markdown.

    Args:
        url: URL to fetch
        timeout: Request timeout in seconds

    Returns:
        Webpage content as markdown
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }

    try:
        response = await webpage_client().get(
            url,
            headers=headers,
            timeout=timeout,
        )
        response.raise_for_status()
        return markdownify(response.text)
    except Exception as e:
        return f"Error fetching content from {url}: {str(e)}"


def search_client():
    """Create the process-shared HTTP client lazily on its ASGI event loop."""
    global _client
    if _client is None:
        _client = AsyncTavilyClient(api_key=TAVILY_API_KEY)
    return _client


def webpage_client():
    """Return the process-shared non-blocking webpage HTTP client."""
    global _web_client
    if _web_client is None:
        _web_client = httpx.AsyncClient(
            follow_redirects=True,
            limits=httpx.Limits(
                max_connections=20,
                max_keepalive_connections=10,
            ),
        )
    return _web_client


async def close_search():
    """Release search HTTP connection pools during ASGI shutdown."""
    global _client, _web_client
    search, _client = _client, None
    web, _web_client = _web_client, None
    if search is not None:
        await search.close()
    if web is not None:
        await web.aclose()


async def internet_search(
    query: str,
    max_results: int = 3,
    topic: Literal["general", "news", "finance"] = "general",
    include_raw_content: bool = False,
):
    """Search the web for information on a given query.

    Uses Tavily to discover relevant URLs, then fetches and returns full webpage content as markdown.

    Args:
        query: Search query to execute
        max_results: Maximum number of results to return (default: 1)
        topic: Topic filter - 'general', 'news', or 'finance' (default: 'general')

    Returns:
        Formatted search results with full webpage content
    """
    return await search_client().search(
        query,
        max_results=max_results,
        include_raw_content=include_raw_content,
        topic=topic,
    )
