"""Company-independent internet search and bounded public-page fetching."""

import asyncio
import ipaddress
import math
import socket
from typing import Literal
from urllib.parse import urljoin, urlsplit

import httpx

from markdownify import markdownify

from tavily import AsyncTavilyClient

from deep_agent_app.utilities.constants import TAVILY_API_KEY

_client = None
MAX_WEB_REDIRECTS = 5
MAX_WEB_BYTES = 500_000
MAX_WEB_CHARS = 20_000
MAX_WEB_TIMEOUT = 30.0
WEB_CONTENT_TYPES = frozenset({"text/html", "text/plain", "application/xhtml+xml"})


def _public_web_url(url: str) -> str:
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("URL must be a public HTTP(S) address without credentials")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("URL has an invalid port") from exc
    if port is not None and port not in {80, 443}:
        raise ValueError("URL port is not allowed")
    return parsed.hostname


def _check_public_host(hostname: str) -> None:
    try:
        addresses = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ValueError("URL host could not be resolved") from exc
    if not addresses or any(
        not ipaddress.ip_address(item[4][0]).is_global for item in addresses
    ):
        raise ValueError("URL host is not public")


async def fetch_webpage_content(url: str, timeout: float = 30.0) -> str:
    """Fetch and convert webpage content to markdown.

    Args:
        url: URL to fetch
        timeout: Request timeout in seconds

    Returns:
        Webpage content as markdown
    """
    headers = {"User-Agent": "DeepAgent-WebFetcher/1.0"}
    try:
        bounded_timeout = float(timeout)
        if not math.isfinite(bounded_timeout) or bounded_timeout <= 0:
            raise ValueError("timeout must be positive and finite")
        bounded_timeout = min(bounded_timeout, MAX_WEB_TIMEOUT)
        async with asyncio.timeout(bounded_timeout):
            async with webpage_client() as client:
                current_url = url
                for redirect_number in range(MAX_WEB_REDIRECTS + 1):
                    hostname = _public_web_url(current_url)
                    await asyncio.to_thread(_check_public_host, hostname)
                    async with client.stream(
                        "GET", current_url, headers=headers, timeout=bounded_timeout
                    ) as response:
                        if response.is_redirect:
                            if redirect_number == MAX_WEB_REDIRECTS:
                                raise ValueError("too many redirects")
                            location = response.headers.get("location")
                            if not location:
                                raise ValueError("redirect has no destination")
                            current_url = urljoin(current_url, location)
                            continue
                        response.raise_for_status()
                        content_type = (
                            response.headers.get("content-type", "")
                            .split(";", 1)[0]
                            .lower()
                        )
                        if content_type not in WEB_CONTENT_TYPES:
                            raise ValueError("unsupported webpage content type")
                        data = bytearray()
                        async for chunk in response.aiter_bytes():
                            if len(data) + len(chunk) > MAX_WEB_BYTES:
                                raise ValueError("webpage exceeds size limit")
                            data.extend(chunk)
                        try:
                            body = data.decode(
                                response.encoding or "utf-8", errors="replace"
                            )
                        except LookupError:
                            body = data.decode("utf-8", errors="replace")
                        result = (
                            markdownify(body) if content_type != "text/plain" else body
                        )
                        if len(result) > MAX_WEB_CHARS:
                            return (
                                result[:MAX_WEB_CHARS]
                                + "\n\n[Webpage content truncated]"
                            )
                        return result
    except ValueError as exc:
        return f"Error fetching webpage: {exc}"
    except httpx.HTTPStatusError as exc:
        return f"Error fetching webpage: HTTP {exc.response.status_code}"
    except httpx.TimeoutException:
        return "Error fetching webpage: request timed out"
    except TimeoutError:
        return "Error fetching webpage: request timed out"
    except httpx.HTTPError:
        return "Error fetching webpage: network request failed"


def search_client():
    """Create the process-shared HTTP client lazily on its ASGI event loop."""
    global _client
    if _client is None:
        _client = AsyncTavilyClient(api_key=TAVILY_API_KEY)
    return _client


def webpage_client():
    """Use a fresh cookie jar so one user's page cannot affect another's fetch."""
    return httpx.AsyncClient(follow_redirects=False, trust_env=False)


async def close_search():
    """Release search HTTP connection pools during ASGI shutdown."""
    global _client
    search, _client = _client, None
    if search is not None:
        await search.close()


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
