# Emby Clean

Emby Clean is a small Docker service for auditing and cleaning duplicate or low-quality Emby media entries. It focuses on safe review workflows: sync metadata locally, scan by library and rule, review grouped candidates, then enqueue confirmed deletes one by one.

## Features

- Emby metadata sync with per-library progress and persistent logs.
- Library-level cache reconciliation: media cache, Emby media count, and API item count.
- Duplicate scans:
  - AV code duplicates
  - Smart edition matching for names that differ only by tags such as `-C`, `-UC`, `4K`
  - Same-size duplicates
  - Same-duration duplicates
  - Missing poster
  - Tiny files
- Poster preview through a local image proxy.
- Review-aware AV priority:
  - `破解-C > C > 破解 > 无标签`
  - `流出 / 泄露 / leak` is marked for manual review and is not auto-selected.
- Safe delete queue:
  - New delete requests append to the queue while the worker is running.
  - Deletes are processed sequentially.
  - The worker waits until Emby no longer returns the item before moving on.

## Quick Start

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
    image: your-dockerhub-user/emby-clean:latest
    ports:
      - "19898:19898"
    volumes:
      - ./data:/data
    restart: unless-stopped
```

The SQLite database is stored under `/data`.

## Safety Notes

- Do not expose this service directly to the public internet.
- Delete actions are destructive in Emby. Always review selected items before queueing deletion.
- The delete worker confirms the item has disappeared from Emby before continuing, but storage backends may still have their own delays.

