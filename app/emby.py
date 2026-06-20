from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import httpx


# How many seconds before we proactively consider the token might be stale
# even if Emby hasn't returned 401 yet.  Emby tokens typically last ~24h.
TOKEN_PROACTIVE_REFRESH_SECONDS = 20 * 3600  # 20 hours


class EmbyError(RuntimeError):
    pass


@dataclass
class EmbySession:
    host: str
    user_id: str
    access_token: str
    server_id: str = ""
    server_name: str = ""
    server_version: str = ""
    user_name: str = ""


def normalize_host(host: str) -> str:
    host = (host or "").strip()
    if host and not host.startswith(("http://", "https://")):
        host = "http://" + host
    return host.rstrip("/")


def auth_headers(token: str) -> dict[str, str]:
    return {
        "X-Emby-Authorization": (
            'MediaBrowser Client="EmbyClean", Device="Docker", '
            'DeviceId="emby-clean", Version="2.0"'
        ),
        "X-Emby-Token": token,
    }


class EmbyClient:
    """Emby API client with automatic token re-authentication.

    When the stored ``access_token`` expires (Emby returns 401), the client
    transparently re-authenticates using the stored username + password and
    retries the original request — provided ``auto_reauth`` is *True* and
    valid credentials were supplied at construction time.
    """

    def __init__(
        self,
        host: str,
        token: str = "",
        user_id: str = "",
        *,
        username: str = "",
        password: str = "",
        auto_reauth: bool = True,
    ):
        self.host = normalize_host(host)
        self.token = token
        self.user_id = user_id
        self._username = username
        self._password = password
        self._auto_reauth = auto_reauth and bool(username)
        self._last_auth_ts: float = 0.0

    # ------------------------------------------------------------------
    #  Authentication
    # ------------------------------------------------------------------

    async def authenticate(self, username: str = "", password: str = "") -> EmbySession:
        """Authenticate against Emby and return a fresh session.

        Falls back to the credentials supplied at construction time when no
        arguments are passed — this is the *re-authentication* path used by
        the automatic token renewal logic.
        """
        username = username or self._username
        password = password or self._password
        if not self.host:
            raise EmbyError("Emby 地址为空")
        if not username:
            raise EmbyError("缺少用户名，无法重新认证")
        payload = {"Username": username, "Pw": password}
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                f"{self.host}/Users/AuthenticateByName",
                headers=auth_headers(""),
                json=payload,
            )
            if resp.status_code >= 400:
                raise EmbyError(f"认证失败：HTTP {resp.status_code}")
            data = resp.json()
        user = data.get("User") or {}
        server = data.get("SessionInfo") or {}
        token = data.get("AccessToken") or ""
        if not token or not user.get("Id"):
            raise EmbyError("认证响应缺少 AccessToken 或 User.Id")
        self.token = token
        self.user_id = user["Id"]
        self._last_auth_ts = time.time()
        return EmbySession(
            host=self.host,
            user_id=user["Id"],
            access_token=token,
            server_id=data.get("ServerId") or server.get("ServerId") or "",
            server_name=data.get("ServerName") or server.get("ServerName") or "",
            server_version=data.get("ServerVersion") or "",
            user_name=user.get("Name") or username,
        )

    async def _ensure_authenticated(self) -> None:
        """Proactively re-authenticate before the token is likely to expire."""
        if not self._auto_reauth:
            return
        if not self._last_auth_ts and self.token:
            self._last_auth_ts = time.time()
        if not self.token or (
            self._last_auth_ts
            and (time.time() - self._last_auth_ts) > TOKEN_PROACTIVE_REFRESH_SECONDS
        ):
            await self.authenticate()

    async def _reauth_and_retry(self, status_code: int) -> bool:
        """Attempt to recover from a 401 by re-authenticating.

        Returns ``True`` if a fresh token was obtained, meaning the caller
        should retry the original request.
        """
        if status_code != 401 or not self._auto_reauth:
            return False
        try:
            await self.authenticate()
            return True
        except EmbyError:
            return False

    # ------------------------------------------------------------------
    #  HTTP helpers (with automatic re-auth on 401)
    # ------------------------------------------------------------------

    async def system_info(self) -> dict[str, Any]:
        return await self.get_json("/System/Info")

    async def me(self) -> dict[str, Any]:
        if not self.user_id:
            return {}
        return await self.get_json(f"/Users/{self.user_id}")

    async def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if not self.host:
            raise EmbyError("Emby 地址为空")
        await self._ensure_authenticated()
        url = urljoin(self.host + "/", path.lstrip("/"))
        async with httpx.AsyncClient(timeout=45) as client:
            resp = await client.get(url, headers=auth_headers(self.token), params=params)
            if resp.status_code == 401 and await self._reauth_and_retry(401):
                resp = await client.get(
                    url, headers=auth_headers(self.token), params=params
                )
            if resp.status_code >= 400:
                raise EmbyError(f"{path} HTTP {resp.status_code}: {resp.text[:200]}")
            return resp.json()

    async def post(self, path: str, params: dict[str, Any] | None = None) -> Any:
        await self._ensure_authenticated()
        url = urljoin(self.host + "/", path.lstrip("/"))
        async with httpx.AsyncClient(timeout=45) as client:
            resp = await client.post(
                url, headers=auth_headers(self.token), params=params
            )
            if resp.status_code == 401 and await self._reauth_and_retry(401):
                resp = await client.post(
                    url, headers=auth_headers(self.token), params=params
                )
            if resp.status_code >= 400:
                raise EmbyError(f"{path} HTTP {resp.status_code}: {resp.text[:200]}")
            if not resp.text:
                return {"ok": True}
            return resp.json() if "json" in resp.headers.get("content-type", "") else {"ok": True}

    async def delete(self, item_id: str) -> None:
        await self._ensure_authenticated()
        async with httpx.AsyncClient(timeout=45) as client:
            resp = await client.delete(
                f"{self.host}/Items/{item_id}",
                headers=auth_headers(self.token),
            )
            if resp.status_code == 401 and await self._reauth_and_retry(401):
                resp = await client.delete(
                    f"{self.host}/Items/{item_id}",
                    headers=auth_headers(self.token),
                )
            if resp.status_code >= 400:
                raise EmbyError(f"删除 {item_id} 失败：HTTP {resp.status_code}")

    async def item_exists(self, item_id: str) -> bool:
        if not self.user_id:
            raise EmbyError("缺少 user_id，请先保存配置")
        await self._ensure_authenticated()
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(
                f"{self.host}/Users/{self.user_id}/Items/{item_id}",
                headers=auth_headers(self.token),
            )
            if resp.status_code == 401 and await self._reauth_and_retry(401):
                resp = await client.get(
                    f"{self.host}/Users/{self.user_id}/Items/{item_id}",
                    headers=auth_headers(self.token),
                )
            if resp.status_code == 404:
                return False
            if resp.status_code >= 400:
                raise EmbyError(f"确认 {item_id} 删除状态失败：HTTP {resp.status_code}")
            return True

    # ------------------------------------------------------------------
    #  Library / item helpers
    # ------------------------------------------------------------------

    async def libraries(self) -> list[dict[str, Any]]:
        if not self.user_id:
            raise EmbyError("缺少 user_id，请先保存配置")
        data = await self.get_json(f"/Users/{self.user_id}/Views")
        return data.get("Items", data if isinstance(data, list) else [])

    async def iter_items(self, library_ids: list[str] | None = None, page_size: int = 500, include_item_types: str = ""):
        if not self.user_id:
            raise EmbyError("缺少 user_id，请先保存配置")
        parent_ids = ",".join(library_ids or [])
        start = 0
        while True:
            data = await self.items_page(parent_ids, start, page_size, include_item_types)
            items = data.get("Items", [])
            for item in items:
                yield item
            total = int(data.get("TotalRecordCount") or 0)
            start += len(items)
            if not items or start >= total:
                break
            await asyncio.sleep(0)

    async def items_page(self, parent_ids: str, start: int = 0, limit: int = 500, include_item_types: str = "") -> dict[str, Any]:
        if not self.user_id:
            raise EmbyError("缺少 user_id，请先保存配置")
        fields = ",".join(
            [
                "Path",
                "MediaSources",
                "ProviderIds",
                "Tags",
                "SortName",
                "ParentId",
                "SeriesId",
                "SeriesName",
                "RunTimeTicks",
                "ImageTags",
                "MediaStreams",
                "DateCreated",
                "PremiereDate",
                "Overview",
                "Genres",
                "Studios",
                "People",
            ]
        )
        params: dict[str, Any] = {
            "Recursive": "true",
            "Fields": fields,
            "StartIndex": start,
            "Limit": limit,
        }
        if include_item_types:
            params["IncludeItemTypes"] = include_item_types
        if parent_ids:
            params["ParentId"] = parent_ids
        return await self.get_json(f"/Users/{self.user_id}/Items", params)

    async def refresh_item(self, item_id: str) -> None:
        await self.post(
            f"/Items/{item_id}/Refresh",
            {
                "Recursive": "true",
                "MetadataRefreshMode": "FullRefresh",
                "ImageRefreshMode": "FullRefresh",
                "ReplaceAllMetadata": "false",
                "ReplaceAllImages": "false",
            },
        )

    async def refresh_library(self) -> None:
        """Trigger a full library scan on the Emby server."""
        await self.post("/Library/Refresh")

    async def get_item(self, item_id: str) -> dict[str, Any]:
        """Fetch a single item's full metadata."""
        return await self.get_json(f"/Users/{self.user_id}/Items/{item_id}")

    async def get_virtual_folders(self) -> list[dict[str, Any]]:
        """List Emby virtual folders / library directories."""
        data = await self.get_json("/Library/VirtualFolders")
        return data if isinstance(data, list) else []

    async def get_server_storage(self) -> list[dict[str, Any]]:
        """Fetch server storage / disk info from Emby."""
        try:
            data = await self.get_json("/System/MediaEncoder")
            return data if isinstance(data, list) else []
        except EmbyError:
            return []

    async def search(self, term: str, limit: int = 50, item_types: str = "", media_types: str = "") -> list[dict[str, Any]]:
        """Search the Emby library for items."""
        params: dict[str, Any] = {
            "SearchTerm": term,
            "Limit": limit,
            "Recursive": "true",
            "Fields": "Path,MediaSources,ProviderIds,Tags,SortName,RunTimeTicks,ImageTags,MediaStreams",
        }
        if item_types:
            params["IncludeItemTypes"] = item_types
        if media_types:
            params["MediaTypes"] = media_types
        data = await self.get_json(f"/Users/{self.user_id}/Items", params)
        return data.get("Items", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
