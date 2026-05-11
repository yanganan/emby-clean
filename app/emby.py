from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import httpx


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
            'DeviceId="emby-clean", Version="1.0"'
        ),
        "X-Emby-Token": token,
    }


class EmbyClient:
    def __init__(self, host: str, token: str = "", user_id: str = ""):
        self.host = normalize_host(host)
        self.token = token
        self.user_id = user_id

    async def authenticate(self, username: str, password: str) -> EmbySession:
        if not self.host:
            raise EmbyError("Emby 地址为空")
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
        return EmbySession(
            host=self.host,
            user_id=user["Id"],
            access_token=token,
            server_id=data.get("ServerId") or server.get("ServerId") or "",
            server_name=data.get("ServerName") or server.get("ServerName") or "",
            server_version=data.get("ServerVersion") or "",
            user_name=user.get("Name") or username,
        )

    async def system_info(self) -> dict[str, Any]:
        return await self.get_json("/System/Info")

    async def me(self) -> dict[str, Any]:
        if not self.user_id:
            return {}
        return await self.get_json(f"/Users/{self.user_id}")

    async def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if not self.host:
            raise EmbyError("Emby 地址为空")
        async with httpx.AsyncClient(timeout=45) as client:
            resp = await client.get(
                urljoin(self.host + "/", path.lstrip("/")),
                headers=auth_headers(self.token),
                params=params,
            )
            if resp.status_code >= 400:
                raise EmbyError(f"{path} HTTP {resp.status_code}: {resp.text[:200]}")
            return resp.json()

    async def post(self, path: str, params: dict[str, Any] | None = None) -> Any:
        async with httpx.AsyncClient(timeout=45) as client:
            resp = await client.post(
                urljoin(self.host + "/", path.lstrip("/")),
                headers=auth_headers(self.token),
                params=params,
            )
            if resp.status_code >= 400:
                raise EmbyError(f"{path} HTTP {resp.status_code}: {resp.text[:200]}")
            if not resp.text:
                return {"ok": True}
            return resp.json() if "json" in resp.headers.get("content-type", "") else {"ok": True}

    async def delete(self, item_id: str) -> None:
        async with httpx.AsyncClient(timeout=45) as client:
            resp = await client.delete(
                f"{self.host}/Items/{item_id}",
                headers=auth_headers(self.token),
            )
            if resp.status_code >= 400:
                raise EmbyError(f"删除 {item_id} 失败：HTTP {resp.status_code}")

    async def item_exists(self, item_id: str) -> bool:
        if not self.user_id:
            raise EmbyError("缺少 user_id，请先保存配置")
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(
                f"{self.host}/Users/{self.user_id}/Items/{item_id}",
                headers=auth_headers(self.token),
            )
            if resp.status_code == 404:
                return False
            if resp.status_code >= 400:
                raise EmbyError(f"确认 {item_id} 删除状态失败：HTTP {resp.status_code}")
            return True

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
