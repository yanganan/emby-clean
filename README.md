# Emby Clean

[Docker Hub](https://hub.docker.com/r/xavieryy/emby-clean) · [GitHub](https://github.com/yanganan/emby-clean) · `ghcr.io/yanganan/emby-clean:latest`

Emby Clean is a small Docker service for auditing and cleaning duplicate or low-quality Emby media entries. It focuses on safe review workflows: sync metadata locally, scan by library and rule, review grouped candidates, then enqueue confirmed deletes one by one.

## Features

### Core
- Emby metadata sync with per-library progress and persistent logs.
- Library-level cache reconciliation: media cache, Emby media count, and API item count.
- Poster preview through a local image proxy.
- Review-aware AV priority: `破解-C > C > 破解 > 无标签`; `流出/泄露/leak` → manual review.
- Safe sequential delete queue: waits until Emby confirms item is gone before proceeding.

### v2.0 新增
- **🔑 Token 自动续期**：access_token 过期后自动使用存储的密码重新认证，彻底解决重启后/过期后配置"丢失"问题。
- **📢 Webhook 实际通知**：同步完成、删除完成、定时任务执行时自动推送通知。
- **⏰ 定时任务**：支持创建定时扫描任务，可开启「自动删除」模式自动清理推荐项。
- **🔄 删除后自动刷新**：批量删除完成后自动触发 Emby 库扫描 (`/Library/Refresh`)。
- **🔁 删除队列自动重试**：失败项自动重试（可配置最大次数），也可手动一键重试。
- **📊 存储仪表盘**：按媒体库统计占用空间、无封面数、无时长数。
- **🔍 新增扫描模式**：
  - `无元数据` — 检测缺少 TMDB/IMDB 等 Provider ID 的媒体
  - `无字幕` — 检测无字幕轨道的媒体
  - `空库检测` — 检测零媒体的空库

### Scan modes
- AV code duplicates
- Smart edition matching for names that differ only by tags such as `-C`, `-UC`, `4K`
- Same-size duplicates
- Same-duration duplicates
- Missing poster
- Tiny files
- Missing metadata (no Provider IDs)
- Missing subtitles (no subtitle stream)
- Empty library detection

## Quick Start

Use Docker Hub:

```bash
docker run -d \
  --name emby-clean \
  --restart unless-stopped \
  -p 19898:19898 \
  -e TZ=Asia/Shanghai \
  -v "$PWD/data:/data" \
  xavieryy/emby-clean:latest
```

Or build from source:

```bash
docker compose up -d --build
```

Open:

```text
http://localhost:19898
```

Then:

1. Open **系统配置**.
2. Fill in Emby URL, username, and password.
3. Save the config.
4. Click **立即同步元数据**.
5. Use **扫描配置** to choose libraries and a scan mode.
6. Review and enqueue deletes from **扫描结果**.

## Docker Compose

```yaml
services:
  emby-clean:
    image: xavieryy/emby-clean:latest
    container_name: emby-clean
    restart: unless-stopped
    ports:
      - "19898:19898"
    environment:
      - TZ=Asia/Shanghai
      - EMBY_CLEAN_DATA=/data
    volumes:
      - ./data:/data
```

The SQLite database is stored under `/data`.

You can also use the GitHub Container Registry image:

```yaml
image: ghcr.io/yanganan/emby-clean:latest
```

## Images

- Docker Hub: `xavieryy/emby-clean:latest`
- GitHub Container Registry: `ghcr.io/yanganan/emby-clean:latest`
- Supported platforms: `linux/amd64`, `linux/arm64`

## GitHub Project

The source code, issues, release tags, and automated build workflow are hosted at:

```text
https://github.com/yanganan/emby-clean
```

The repository includes:

- `Dockerfile` for containerized deployment.
- `docker-compose.yml` for local source builds.
- `.github/workflows/docker-publish.yml` for automatic multi-platform image publishing.
- `docs/DEPLOYMENT.md` for deployment and release operations.
- `docs/DOCKERHUB.md` with a Docker Hub Overview template.

## Safety Notes

- Do not expose this service directly to the public internet.
- Delete actions are destructive in Emby. Always review selected items before queueing deletion.
- The delete worker confirms the item has disappeared from Emby before continuing, but storage backends may still have their own delays.
