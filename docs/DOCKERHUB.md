# Docker Hub Overview

Emby Clean is a self-hosted Docker service for auditing and cleaning Emby media libraries. It syncs Emby metadata into a local cache, scans for duplicate or suspicious media entries, shows review-friendly results, and deletes confirmed items through a safe queue.

## Features

- Emby metadata sync with persistent logs.
- Dynamic library discovery from Emby instead of hard-coded library names.
- Duplicate scan modes for AV code, smart edition names, same size, same duration, missing poster, and tiny files.
- Poster previews through a local image proxy.
- Review-aware AV priority: `破解-C > C > 破解 > 无标签`.
- `流出 / 泄露 / leak` entries are marked for manual review and are not auto-selected.
- Sequential delete queue that waits for Emby confirmation before processing the next item.
- Local SQLite storage for config, cache, logs, scan records, and delete queue state.

## Quick Start

```bash
docker run -d \
  --name emby-clean \
  --restart unless-stopped \
  -p 19898:19898 \
  -e TZ=Asia/Shanghai \
  -v "$PWD/data:/data" \
  xavieryy/emby-clean:latest
```

Open:

```text
http://localhost:19898
```

Then open the system config page, fill in your Emby URL, username, and password, save the config, and start metadata sync.

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

Start:

```bash
docker compose up -d
```

Upgrade:

```bash
docker compose pull
docker compose up -d
```

## Image Tags

- `latest`: latest build from the `main` branch.
- `vX.Y.Z`: release builds from Git tags.
- `sha-*`: traceable builds for a specific commit.

## Data Persistence

Mount `/data` to persist:

- Emby connection config
- synced media cache
- library metadata
- logs
- delete queue records
- scan task records

Do not run this container without a persistent volume if you want cache and logs to survive upgrades.

## Security Notes

- Do not expose this service directly to the public internet.
- Put it behind a trusted LAN, VPN, or reverse proxy with authentication.
- Delete operations are destructive in Emby. Always review selected items before queueing deletion.

## Source Code

GitHub repository:

```text
https://github.com/yanganan/emby-clean
```

GitHub Container Registry image:

```text
ghcr.io/yanganan/emby-clean:latest
```
