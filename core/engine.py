import asyncio
import json
import logging
import os
import random
import re
import time
import uuid
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from typing import AsyncGenerator, Dict, List, Optional, Tuple, Any
from urllib.parse import parse_qs, parse_qsl, quote, urlparse

import aiohttp
from aiohttp import ClientTimeout, TCPConnector
from bs4 import BeautifulSoup

from core.models import (
    CheckStatus,
    EventType,
    SiteCheckOutcome,
    SiteResult,
    StreamEvent,
)

logger = logging.getLogger("metis.engine")

try:
    from socid_extractor import extract
except ImportError:
    extract = None
    logger.warning("socid_extractor not installed. Profile extraction disabled.")


class RateLimiter:
    """Rate limiter for outbound requests per domain."""
    def __init__(self, max_requests: int = 100, time_window: int = 60):
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = defaultdict(list)
        self._lock = asyncio.Lock()

    async def wait_if_needed(self, domain: str) -> float:
        """Wait if rate limit would be exceeded, return wait time."""
        async with self._lock:
            now = time.time()
            self.requests[domain] = [
                t for t in self.requests[domain]
                if now - t < self.time_window
            ]

            if len(self.requests[domain]) >= self.max_requests:
                sleep_time = self.time_window - (now - self.requests[domain][0])
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)
                    self.requests[domain].clear()
                    self.requests[domain].append(time.time())
                    return sleep_time

            self.requests[domain].append(now)
            return 0


class UsernameSearchEngine:
    """Asynchronous engine for scanning usernames across web platforms."""

    def __init__(
        self,
        max_concurrent_requests: int = 30,
        timeout_seconds: int = 10,
        max_retries: int = 1,
        stream_delay: float = 0.02,
        data_file: Optional[str] = None,
    ):
        self.max_concurrent_requests = max_concurrent_requests
        self.timeout = ClientTimeout(total=timeout_seconds)
        self.max_retries = max_retries
        self.stream_delay = stream_delay
        self._metadata_cache = None
        self.rate_limiter = RateLimiter()
        self.semaphore = asyncio.Semaphore(max_concurrent_requests)

        # Default local cached database path
        if data_file:
            self.local_data_path = Path(data_file)
        else:
            self.local_data_path = Path(__file__).parent / "data" / "wmn-data.json"

        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
        ]

        self.base_headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
        }

        self._url_pattern = re.compile(r"\{account\}")
        self._regex_cache = {}
        self._account_confirmation_sites = {
            "Arch Linux GitLab",
            "Fanslist (OnlyFans)",
            "HackerOne",
            "InkBunny",
            "Mixi",
            "PatientsLikeMe",
            "Pinterest",
            "prv.pl",
            "ru_123rf",
            "thegatewaypundit",
            "Ubisoft",
            "Zbiornik",
        }

    def get_metadata(self) -> dict:
        """Fetch and cache metadata, with local fallback."""
        if self._metadata_cache:
            return self._metadata_cache

        # If local cached file exists, try loading it first if needed or fallback
        url = "https://raw.githubusercontent.com/WebBreacher/WhatsMyName/refs/heads/main/wmn-data.json"
        try:
            import requests
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            self._metadata_cache = response.json()
            # Update local cache in background
            try:
                self.local_data_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.local_data_path, "w", encoding="utf-8") as f:
                    f.write(response.text)
            except Exception:
                pass
            return self._metadata_cache
        except Exception as e:
            logger.warning(f"Failed to fetch remote metadata: {e}. Attempting local fallback.")
            if self.local_data_path.exists():
                try:
                    with open(self.local_data_path, "r", encoding="utf-8") as f:
                        self._metadata_cache = json.load(f)
                    return self._metadata_cache
                except Exception as ex:
                    logger.error(f"Failed to read local metadata cache: {ex}")
            raise RuntimeError(f"Could not load WMN site metadata: {e}")

    def get_random_user_agent(self) -> str:
        return random.choice(self.user_agents)

    def _get_compiled_regex(self, pattern: str) -> Optional[re.Pattern]:
        if pattern not in self._regex_cache:
            try:
                self._regex_cache[pattern] = re.compile(pattern, re.IGNORECASE)
            except re.error:
                self._regex_cache[pattern] = None
        return self._regex_cache[pattern]

    def _text_matches_pattern(self, text: str, pattern: Optional[str]) -> bool:
        if pattern is None:
            return False
        if pattern == "":
            return True
        if pattern in text:
            return True
        compiled_pattern = self._get_compiled_regex(pattern)
        return bool(compiled_pattern and compiled_pattern.search(text))

    def _response_confirms_account(self, site: dict, username: str, text: str) -> bool:
        site_name = site.get("name")
        if site_name not in self._account_confirmation_sites:
            return True

        username_folded = username.casefold()
        text_folded = text.casefold()

        if site_name == "Arch Linux GitLab":
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                return False
            if not isinstance(data, list):
                return False
            for item in data:
                if not isinstance(item, dict):
                    continue
                for field in ("username", "path", "name"):
                    value = item.get(field)
                    if isinstance(value, str) and value.casefold() == username_folded:
                        return True
            return False

        if site_name == "Fanslist (OnlyFans)":
            pattern = rf'data-username=["\']{re.escape(username)}["\']'
            return bool(re.search(pattern, text, re.IGNORECASE))

        if site_name == "HackerOne":
            pattern = rf'"username"\s*:\s*"{re.escape(username)}"'
            return bool(re.search(pattern, text, re.IGNORECASE))

        if site_name == "Pinterest":
            title_pattern = rf"\({re.escape(username)}\)\s*-\s*Profile\s*\|\s*Pinterest"
            return bool(re.search(title_pattern, text, re.IGNORECASE))

        if site_name == "thegatewaypundit":
            return f"/author/{username_folded}/" in text_folded

        return username_folded in text_folded

    def _try_parse_json(self, text: str) -> Optional[dict]:
        try:
            text = text.strip()
            if text.startswith(("{", "[")):
                data = json.loads(text)
                if isinstance(data, dict):
                    return data

            brace_start = text.find("{")
            if brace_start != -1:
                brace_count = 0
                for i in range(brace_start, len(text)):
                    if text[i] == "{":
                        brace_count += 1
                    elif text[i] == "}":
                        brace_count -= 1
                        if brace_count == 0:
                            data = json.loads(text[brace_start : i + 1])
                            if isinstance(data, dict):
                                return data
                            break
        except (json.JSONDecodeError, ValueError):
            pass
        return None

    async def _check_response_match(
        self,
        response_status: int,
        text: str,
        site: dict,
        redirect_statuses: Optional[List[int]] = None,
    ) -> Tuple[bool, bool]:
        redirect_statuses = redirect_statuses or []

        if "m_code" in site and site["m_code"] in redirect_statuses:
            return False, True

        if "m_code" in site and response_status == site["m_code"]:
            m_string = site.get("m_string")
            if self._text_matches_pattern(text, m_string):
                return False, True

        if response_status == site.get("e_code"):
            e_string = site.get("e_string")
            if self._text_matches_pattern(text, e_string):
                return True, False

        return False, False

    async def check_single_site(
        self,
        session: aiohttp.ClientSession,
        site: dict,
        username: str,
        extract_profile: bool = False,
    ) -> SiteCheckOutcome:
        placeholder = "{account}"
        url = self._url_pattern.sub(quote(username), site["uri_check"]).replace(
            placeholder, quote(username)
        )
        domain = urlparse(url).netloc

        headers = self.base_headers.copy()
        headers["User-Agent"] = self.get_random_user_agent()
        if "headers" in site:
            headers.update(site["headers"])

        is_post = bool(site.get("post_body"))
        data = None
        json_data = None

        if is_post:
            post_body = site["post_body"].replace(placeholder, username)
            content_type = headers.get("Content-Type", "").lower()
            if "json" in content_type:
                try:
                    json_data = json.loads(post_body)
                except json.JSONDecodeError:
                    json_data = post_body
            elif "form-urlencoded" in content_type:
                data = dict(parse_qsl(post_body))
            else:
                data = post_body

        base_result = {
            "site_name": site["name"],
            "category": site.get("cat", "unknown"),
        }

        if site.get("name") == "Mixi" and not username.isdigit():
            return SiteCheckOutcome(
                result=SiteResult(
                    **base_result,
                    url=url,
                    status=CheckStatus.NOT_FOUND,
                    error_message="Mixi check requires a numeric community id",
                )
            )

        start_time = time.time()

        async with self.semaphore:
            wait_time = await self.rate_limiter.wait_if_needed(domain)
            if wait_time > 0:
                logger.debug(f"Rate limited for {domain}, waited {wait_time:.2f}s")

            try:
                method = "POST" if is_post else "GET"
                request_kwargs = {
                    "url": url,
                    "headers": headers,
                    "timeout": self.timeout,
                    "allow_redirects": True,
                    "ssl": False,
                }

                if is_post:
                    if isinstance(json_data, dict):
                        request_kwargs["json"] = json_data
                    elif data:
                        request_kwargs["data"] = data

                async with session.request(method, **request_kwargs) as response:
                    raw_bytes = await response.read()
                    try:
                        text = raw_bytes.decode("utf-8")
                    except UnicodeDecodeError:
                        text = raw_bytes.decode("latin-1", errors="ignore")

                    response_time = time.time() - start_time

                    is_found, is_not_found = await self._check_response_match(
                        response.status,
                        text,
                        site,
                        [h.status for h in response.history],
                    )

                    if is_found and not self._response_confirms_account(site, username, text):
                        is_found = False
                        is_not_found = True

                    if is_found:
                        pretty_url = site.get("uri_pretty", site["uri_check"]).replace(
                            "{account}", username
                        )
                        result = SiteResult(
                            **base_result,
                            url=pretty_url,
                            status=CheckStatus.FOUND,
                            status_code=response.status,
                            response_time=response_time,
                        )
                        return SiteCheckOutcome(
                            result=result,
                            response_text=text if extract_profile else None,
                        )
                    elif is_not_found:
                        return SiteCheckOutcome(
                            result=SiteResult(
                                **base_result,
                                url=url,
                                status=CheckStatus.NOT_FOUND,
                                status_code=response.status,
                                response_time=response_time,
                            )
                        )
                    else:
                        return SiteCheckOutcome(
                            result=SiteResult(
                                **base_result,
                                url=url,
                                status=CheckStatus.ERROR,
                                status_code=response.status,
                                error_message="Response does not match pattern",
                                response_time=response_time,
                            )
                        )

            except asyncio.TimeoutError:
                return SiteCheckOutcome(
                    result=SiteResult(
                        **base_result,
                        url=url,
                        status=CheckStatus.ERROR,
                        error_message="Timeout",
                        response_time=time.time() - start_time,
                    )
                )
            except aiohttp.ClientError as e:
                return SiteCheckOutcome(
                    result=SiteResult(
                        **base_result,
                        url=url,
                        status=CheckStatus.ERROR,
                        error_message=f"Client error: {e}",
                        response_time=time.time() - start_time,
                    )
                )
            except Exception as e:
                return SiteCheckOutcome(
                    result=SiteResult(
                        **base_result,
                        url=url,
                        status=CheckStatus.ERROR,
                        error_message=str(e),
                        response_time=time.time() - start_time,
                    )
                )

    async def check_site_with_retry(
        self,
        session: aiohttp.ClientSession,
        site: dict,
        username: str,
        extract_profile: bool = False,
    ) -> SiteCheckOutcome:
        last_result = None
        for attempt in range(max(1, self.max_retries)):
            outcome = await self.check_single_site(session, site, username, extract_profile)
            result = outcome.result

            if result.status in [CheckStatus.FOUND, CheckStatus.NOT_FOUND]:
                return outcome

            last_result = outcome
            if result.error_message and any(
                x in result.error_message.lower()
                for x in ["timeout", "rate limit", "too many"]
            ):
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(0.2 * (2**attempt))
            else:
                break
        return last_result

    async def extract_profile_data(self, text: str, url: str) -> Optional[dict]:
        profile_data = None
        if extract:
            try:
                profile_data = await asyncio.to_thread(extract, text)
            except Exception as e:
                logger.debug(f"socid_extractor failed for {url}: {e}")

        if not profile_data:
            parsed_json = self._try_parse_json(text)
            if parsed_json:
                profile_data = parsed_json

        return profile_data

    async def stream_duckduckgo_search(
        self,
        session: aiohttp.ClientSession,
        username: str,
        queue_event,
    ):
        await queue_event(
            StreamEvent(
                event_type=EventType.DUCKDUCKGO_STARTED,
                data={"message": "Starting DuckDuckGo search"},
            )
        )

        query = quote(f'"{username}"')
        url = f"https://html.duckduckgo.com/html/?q={query}"
        headers = {
            "User-Agent": self.get_random_user_agent(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": "https://html.duckduckgo.com/",
        }

        try:
            async with session.get(url, headers=headers, timeout=self.timeout) as response:
                if response.status == 200:
                    text = await response.text()
                    soup = BeautifulSoup(text, "html.parser")
                    seen_urls = set()

                    for a_tag in soup.find_all("a", class_="result__a", href=True):
                        href = a_tag.get("href", "")
                        real_url = None

                        if "uddg=" in href:
                            parsed_url = urlparse(href)
                            uddg_vals = parse_qs(parsed_url.query).get("uddg")
                            if uddg_vals:
                                real_url = uddg_vals[0]
                        elif href.startswith("http"):
                            real_url = href

                        if real_url and real_url not in seen_urls:
                            seen_urls.add(real_url)
                            domain = urlparse(real_url).netloc.replace("www.", "")
                            if domain and "duckduckgo.com" not in domain:
                                await queue_event(
                                    StreamEvent(
                                        event_type=EventType.DUCKDUCKGO_RESULT,
                                        data={
                                            "url": real_url,
                                            "domain": domain,
                                            "title": a_tag.get_text(strip=True),
                                        },
                                    )
                                )
                                await asyncio.sleep(self.stream_delay)
        except Exception as e:
            logger.error(f"DuckDuckGo search error: {e}")

    async def stream_search(
        self,
        username: str,
        include_duckduckgo: bool = False,
        extract_profile: bool = True,
        categories: Optional[List[str]] = None,
        priority_sites: Optional[List[str]] = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        search_id = str(uuid.uuid4())
        start_time = time.time()

        metadata = self.get_metadata()
        sites = metadata.get("sites", [])

        if categories:
            categories_set = set(c.lower() for c in categories)
            sites = [s for s in sites if s.get("cat", "").lower() in categories_set]

        if priority_sites:
            priority_set = set(p.lower() for p in priority_sites)
            priority = [s for s in sites if s.get("name", "").lower() in priority_set]
            regular = [s for s in sites if s.get("name", "").lower() not in priority_set]
            sites = priority + regular

        yield StreamEvent(
            event_type=EventType.SEARCH_STARTED,
            data={
                "search_id": search_id,
                "username": username,
                "total_sites": len(sites),
                "categories": categories,
                "include_duckduckgo": include_duckduckgo,
                "extract_profile": extract_profile,
            },
        )

        found_count = 0
        not_found_count = 0
        error_count = 0
        checked_count = 0

        result_queue = asyncio.PriorityQueue()
        queue_sequence = 0

        def event_priority(event: StreamEvent) -> int:
            if event.event_type == EventType.PROFILE_EXTRACTED:
                return 0
            if (
                event.event_type == EventType.SITE_RESULT
                and event.data.get("status") == CheckStatus.FOUND.value
            ):
                return 1
            if event.event_type == EventType.SITE_RESULT:
                return 2
            if event.event_type in [EventType.DUCKDUCKGO_RESULT, EventType.DUCKDUCKGO_STARTED]:
                return 3
            return 4

        async def queue_event(event: StreamEvent):
            nonlocal queue_sequence
            seq = queue_sequence
            queue_sequence += 1
            await result_queue.put((event_priority(event), seq, event))

        async def process_site(site: dict):
            await queue_event(
                StreamEvent(
                    event_type=EventType.SITE_CHECKING,
                    data={
                        "site_name": site["name"],
                        "category": site.get("cat", "unknown"),
                        "url": site["uri_check"].replace("{account}", username),
                    },
                )
            )

            outcome = await self.check_site_with_retry(
                session, site, username, extract_profile
            )
            result = outcome.result

            await queue_event(
                StreamEvent(
                    event_type=EventType.SITE_RESULT,
                    data=result.to_dict(),
                )
            )

            if (
                extract_profile
                and result.status == CheckStatus.FOUND
                and outcome.response_text
            ):
                profile_data = await self.extract_profile_data(
                    outcome.response_text, result.url
                )
                if profile_data:
                    result.profile_data = profile_data
                    await queue_event(
                        StreamEvent(
                            event_type=EventType.PROFILE_EXTRACTED,
                            data={
                                "site_name": result.site_name,
                                "category": result.category,
                                "url": result.url,
                                "profile_data": profile_data,
                                "checked_at": result.checked_at,
                            },
                        )
                    )

        connector = TCPConnector(
            limit=self.max_concurrent_requests,
            limit_per_host=5,
            ttl_dns_cache=300,
            force_close=False,
            enable_cleanup_closed=True,
        )

        async with aiohttp.ClientSession(
            connector=connector,
            timeout=self.timeout,
            trust_env=True,
        ) as session:
            tasks = [asyncio.create_task(process_site(s)) for s in sites]
            if include_duckduckgo:
                tasks.append(
                    asyncio.create_task(
                        self.stream_duckduckgo_search(session, username, queue_event)
                    )
                )

            total_sites = len(sites)

            while any(not t.done() for t in tasks) or not result_queue.empty():
                try:
                    _, _, event = await asyncio.wait_for(result_queue.get(), timeout=1.0)
                    if event.event_type == EventType.SITE_RESULT:
                        checked_count += 1
                        site_data = event.data
                        if site_data["status"] == CheckStatus.FOUND.value:
                            found_count += 1
                        elif site_data["status"] == CheckStatus.NOT_FOUND.value:
                            not_found_count += 1
                        else:
                            error_count += 1

                        pct = round((checked_count / total_sites) * 100, 2) if total_sites > 0 else 0
                        event.data["progress"] = {
                            "checked": checked_count,
                            "total": total_sites,
                            "found": found_count,
                            "not_found": not_found_count,
                            "errors": error_count,
                            "percentage": pct,
                        }

                    yield event
                    if event.event_type == EventType.DUCKDUCKGO_RESULT and self.stream_delay > 0:
                        await asyncio.sleep(self.stream_delay)

                except asyncio.TimeoutError:
                    if all(t.done() for t in tasks):
                        break
                    continue

            await asyncio.gather(*tasks, return_exceptions=True)

            while not result_queue.empty():
                _, _, event = await result_queue.get()
                if event.event_type == EventType.SITE_RESULT:
                    checked_count += 1
                    site_data = event.data
                    if site_data["status"] == CheckStatus.FOUND.value:
                        found_count += 1
                    elif site_data["status"] == CheckStatus.NOT_FOUND.value:
                        not_found_count += 1
                    else:
                        error_count += 1

                    pct = round((checked_count / total_sites) * 100, 2) if total_sites > 0 else 0
                    event.data["progress"] = {
                        "checked": checked_count,
                        "total": total_sites,
                        "found": found_count,
                        "not_found": not_found_count,
                        "errors": error_count,
                        "percentage": pct,
                    }

                yield event
                if event.event_type == EventType.DUCKDUCKGO_RESULT and self.stream_delay > 0:
                    await asyncio.sleep(self.stream_delay)

        elapsed = time.time() - start_time
        yield StreamEvent(
            event_type=EventType.SEARCH_COMPLETED,
            data={
                "search_id": search_id,
                "username": username,
                "total_found": found_count,
                "total_not_found": not_found_count,
                "total_errors": error_count,
                "total_checked": checked_count,
                "search_time_seconds": round(elapsed, 2),
                "success_rate": round((found_count / checked_count) * 100, 2)
                if checked_count > 0
                else 0,
            },
        )

    async def search_username(
        self,
        username: str,
        include_duckduckgo: bool = False,
        extract_profile: bool = True,
        categories: Optional[List[str]] = None,
        priority_sites: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Convenience method to run full search and aggregate results."""
        collected_results = []
        profile_map = {}
        ddg_results = []
        stats = {}

        async for event in self.stream_search(
            username=username,
            include_duckduckgo=include_duckduckgo,
            extract_profile=extract_profile,
            categories=categories,
            priority_sites=priority_sites,
        ):
            if event.event_type == EventType.SITE_RESULT and event.data.get("status") == "found":
                collected_results.append(event.data)
            elif event.event_type == EventType.PROFILE_EXTRACTED:
                key = (event.data.get("site_name"), event.data.get("url"))
                profile_map[key] = event.data.get("profile_data")
            elif event.event_type == EventType.DUCKDUCKGO_RESULT:
                ddg_results.append(event.data)
            elif event.event_type == EventType.SEARCH_COMPLETED:
                stats = event.data

        # Merge profile data into results
        for item in collected_results:
            key = (item.get("site_name"), item.get("url"))
            if key in profile_map:
                item["profile_data"] = profile_map[key]

        return {
            "username": username,
            "stats": stats,
            "results": collected_results,
            "duckduckgo_results": ddg_results,
        }
