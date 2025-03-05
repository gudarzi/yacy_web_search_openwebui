"""
title: Web Search using YaCy (The Decentralized Web Search Engine)
author: Ehsan Gudarzi
author_url: https://gudarzi.com
version: 1.1
license: MIT
"""
import asyncio
import aiohttp
from typing import Callable, Any, Optional, List
from urllib.parse import quote
from pydantic import BaseModel, Field
from bs4 import BeautifulSoup
EmitterType = Optional[Callable[[dict], Any]]
class EventEmitter:
    def __init__(self, event_emitter: EmitterType):
        self.event_emitter = event_emitter
    async def emit(self, event_type: str, data: dict):
        if self.event_emitter:
            await self.event_emitter({"type": event_type, "data": data})
    async def update_status(
        self, description: str, done: bool, action: str, urls: List[str]
    ):
        await self.emit(
            "status",
            {"done": done, "action": action, "description": description, "urls": urls},
        )
    async def send_citation(self, title: str, url: str, content: str):
        await self.emit(
            "citation",
            {
                "document": [content],
                "metadata": [{"name": title, "source": url, "html": False}],
            },
        )
class Tools:
    def __init__(self):
        self.valves = self.Valves()
    class Valves(BaseModel):
        YACY_URL: str = Field(
            default="https://ya.gudarzi.com/solr/select",
            description="The base URL for the YaCy search engine",
        )
        PAGES_NO: int = Field(
            default=10,
            description="Number of search results to retrieve",
        )
        PAGE_CONTENT_WORDS_LIMIT: int = Field(
            default=2000,
            description="Truncation length for web content",
        )
    async def yacy_search(
        self, query: str, user_request: str, __event_emitter__: EmitterType = None
    ) -> str:
        """
        Searches the web using the a private YaCy instance based on the query content and returns links and descriptions.
        This function is called only if a search request is explicitly made.
        :param query: The search query
        :param user_request: The user's original request or query
        :param __event_emitter__: Optional event emitter for status updates
        :return: Combined results from search
        """
        emitter = EventEmitter(__event_emitter__)
        if not self.valves.YACY_URL:
            await emitter.update_status(
                "Please set the YaCy search URL!", True, "web_search", []
            )
            raise ValueError("Please set the YaCy search URL!")
        await emitter.update_status(
            f"Searching YaCy for: {query}", False, "web_search", []
        )
        encoded_query = quote(query)
        search_url = f"{self.valves.YACY_URL}?hl=false&wt=yjson&facet=true&facet.mincount=1&facet.field=url_file_ext_s&start=0&rows={self.valves.PAGES_NO}&query={encoded_query}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(search_url) as response:
                    response.raise_for_status()
                    search_results = await response.json()
            items = search_results["channels"][0]["items"]
            urls = [item["link"] for item in items]
            titles = [item.get("title", "Title not available") for item in items]
            if not urls:
                await emitter.update_status(
                    "Search returned no results", True, "web_search", []
                )
                return "Search returned no results"
            await emitter.update_status(
                f"Search complete, processing {len(urls)} results",
                False,
                "web_search",
                urls,
            )
            scraped_content = await self.web_scrape(
                urls, titles, user_request, __event_emitter__
            )
            final_result = f"User query about: {query}\nOriginal request: {user_request}\n\nSearch results:\n{scraped_content}"
            await emitter.update_status(
                f"Processed {len(urls)} search results",
                True,
                "web_search",
                urls,
            )
            return final_result
        except aiohttp.ClientError as e:
            error_message = f"Error during search: {str(e)}"
            await emitter.update_status(error_message, True, "web_search", [])
            return error_message
    async def web_scrape(
        self,
        urls: List[str],
        titles: List[str],
        user_request: str,
        __event_emitter__: EmitterType = None,  # Added titles parameter
    ) -> str:
        """
        Scrapes content from provided URLs and returns a summary.
        Call this function when URLs are provided.
        :param urls: List of URLs of the web pages to scrape.
        :param titles: List of titles for the web pages. # Added titles parameter
        :param user_request: The user's original request or query.
        :param __event_emitter__: Optional event emitter for status updates.
        :return: Combined scraped contents, or error messages.
        """
        emitter = EventEmitter(__event_emitter__)
        combined_results = []
        await emitter.update_status(
            f"Fetching content from {len(urls)} URLs", False, "web_scrape", urls
        )
        async def process_url(url, title):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url) as response:
                        response.raise_for_status()
                        content = await response.text()
                soup = BeautifulSoup(content, "html.parser")
                text_content = soup.get_text(separator=' ', strip=True)

                if title == "Title not available":
                    title_tag = soup.find("title")
                    if title_tag:
                        title = title_tag.string.strip()
                    else:
                        title = "Title not available"
                await emitter.send_citation(title, url, text_content)
                return f"# Title: {title}\n# URL: {url}\n# Content: {text_content}\n"
            except aiohttp.ClientError as e:
                error_message = f"Error fetching URL {url}: {str(e)}"
                await emitter.update_status(error_message, False, "web_scrape", [url])
                return (
                    f"# Fetch Failed!\n# URL: {url}\n# Error Message: {error_message}\n"
                )
        tasks = [process_url(url, title) for url, title in zip(urls, titles)]
        results = await asyncio.gather(*tasks)
        combined_results.extend(results)
        await emitter.update_status(
            f"Processed content from {len(urls)} URLs", True, "web_scrape", urls
        )
        return "\n".join(
            [
                " ".join(
                    result.split()[: self.valves.PAGE_CONTENT_WORDS_LIMIT // len(urls)]
                )
                for result in combined_results
            ]
        )