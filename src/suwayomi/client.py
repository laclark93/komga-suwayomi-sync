import logging
from typing import Optional

import aiohttp

from ..config import Settings

logger = logging.getLogger(__name__)


class SuwayomiGraphQLError(Exception):
    """Raised when the Suwayomi GraphQL API returns errors."""

    def __init__(self, errors: list[dict]):
        self.errors = errors
        messages = [e.get("message", str(e)) for e in errors]
        super().__init__(f"Suwayomi GraphQL errors: {'; '.join(messages)}")


class SuwayomiClient:
    """GraphQL client for the Suwayomi API."""

    def __init__(self, settings: Settings):
        base_url = settings.suwayomi_base_url.rstrip("/")
        self._url = f"{base_url}/api/graphql"
        self._session: Optional[aiohttp.ClientSession] = None
        self._auth: Optional[aiohttp.BasicAuth] = None
        if settings.suwayomi_username:
            self._auth = aiohttp.BasicAuth(
                settings.suwayomi_username, settings.suwayomi_password
            )

    async def start(self):
        self._session = aiohttp.ClientSession(auth=self._auth)

    async def close(self):
        if self._session:
            await self._session.close()

    async def _query(self, query: str, variables: Optional[dict] = None) -> dict:
        """Execute a GraphQL query/mutation."""
        payload: dict = {"query": query}
        if variables:
            payload["variables"] = variables

        async with self._session.post(self._url, json=payload) as resp:
            resp.raise_for_status()
            result = await resp.json()
            if "errors" in result:
                raise SuwayomiGraphQLError(result["errors"])
            return result["data"]

    async def get_all_manga_with_chapters(self) -> list[dict]:
        """Fetch all in-library manga with their chapters."""
        query = """
        query {
            mangas(condition: { inLibrary: true }) {
                nodes {
                    id
                    title
                    chapters {
                        nodes {
                            id
                            name
                            chapterNumber
                            isRead
                            sourceOrder
                        }
                    }
                }
            }
        }
        """
        data = await self._query(query)
        manga_list = data["mangas"]["nodes"]
        logger.info("Fetched %d manga from Suwayomi library", len(manga_list))
        return manga_list

    async def mark_chapter_read(self, chapter_id: int) -> None:
        """Mark a single chapter as read."""
        mutation = """
        mutation MarkRead($id: Int!) {
            updateChapter(input: { id: $id, patch: { isRead: true } }) {
                chapter { id isRead }
            }
        }
        """
        await self._query(mutation, {"id": chapter_id})

    async def mark_chapters_read(self, chapter_ids: list[int]) -> None:
        """Mark multiple chapters as read in one call."""
        if not chapter_ids:
            return
        mutation = """
        mutation MarkBatchRead($ids: [Int!]!) {
            updateChapters(input: { ids: $ids, patch: { isRead: true } }) {
                chapters { id isRead }
            }
        }
        """
        await self._query(mutation, {"ids": chapter_ids})
