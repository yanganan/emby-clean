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
- **💾 配置自动备份与恢复**：每次保存配置时自动备份到 `/data/config_backup.json`；容器重建后数据库为空时自动从备份恢复。支持通过 API 手动导出/导入配置。
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

> **⚠️ 重要：更新镜像时务必保留卷挂载 (`-v ./data:/data`)，否则配置和数据会丢失！**

You can also use the GitHub Container Registry image:

```yaml
image: ghcr.io/yanganan/emby-clean:latest
```

## 更新 / 升级

> **容器更新后配置丢失？** 这是因为重建容器时没有挂载数据卷。请按以下方法正确更新。

### Docker Compose（推荐）

```bash
# 拉取最新镜像并重建容器（自动保留 ./data 卷挂载）
docker compose pull
docker compose up -d
```

### Docker Run

```bash
# 1. 停止旧容器
docker stop emby-clean && docker rm emby-clean

# 2. 拉取最新镜像
docker pull xavieryy/emby-clean:latest

# 3. 用相同的参数（包括 -v 卷挂载！）重新创建容器
docker run -d \
  --name emby-clean \
  --restart unless-stopped \
  -p 19898:19898 \
  -e TZ=Asia/Shanghai \
  -v "$PWD/data:/data" \
  xavieryy/emby-clean:latest
```

### NAS Docker 管理界面（飞牛 NAS / 群晖等）

1. **更新前**：在系统配置页点击「导出配置」按钮，保存 JSON 文件到本地。
2. **更新镜像**：通过 NAS 界面拉取新镜像并重建容器。
3. **确保卷挂载**：重建容器时务必添加 `-v /your/path/data:/data` 卷映射。
4. **如果配置丢失**：访问新容器，在系统配置页点击「导入配置」，上传之前导出的 JSON 文件。

### 配置备份与恢复

系统会在每次保存配置时自动将配置备份到 `/data/config_backup.json`。如果容器重建后数据库为空，系统会自动尝试从备份文件恢复配置。

你也可以通过 API 手动操作：

```bash
# 导出配置（包含 Emby 连接信息、偏好设置、定时任务）
curl http://localhost:19898/api/config/export -o emby-clean-backup.json

# 导入配置
curl -X POST http://localhost:19898/api/config/import \
  -H "Content-Type: application/json" \
  -d @emby-clean-backup.json
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
