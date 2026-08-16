# Deployment

## Published Images

Use either published image:

```text
xavieryy/emby-clean:latest
ghcr.io/yanganan/emby-clean:latest
```

The images are built for:

- `linux/amd64`
- `linux/arm64`

## Docker Compose

Create `docker-compose.yml`:

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

Open:

```text
http://SERVER_IP:19898
```

Upgrade:

```bash
docker compose pull
docker compose up -d
```

Stop:

```bash
docker compose down
```

The `./data:/data` volume stores config, cache, logs, and delete queue data.

## Local Build

```bash
docker build -t emby-clean:local .
docker run --rm -p 19898:19898 -v "$PWD/data:/data" emby-clean:local
```

## Docker Hub Automated Publishing

This repository includes a GitHub Actions workflow at:

```text
.github/workflows/docker-publish.yml
```

It builds and pushes multi-platform images to GitHub Container Registry and Docker Hub when:

- code is pushed to `main`
- a tag like `v1.0.0` is pushed
- the workflow is run manually

## Required GitHub Secrets

Docker Hub publishing requires these repository secrets in GitHub:

- `DOCKERHUB_USERNAME`
- `DOCKERHUB_TOKEN`

The token should be a Docker Hub access token, not your Docker Hub account password.

GitHub Container Registry publishing uses the built-in `GITHUB_TOKEN` and does not require extra secrets.

## Image Tags

The workflow publishes:

- `latest` for `main`
- semantic version tags for Git tags like `v1.2.3`
- branch SHA tags for traceability

## Release Flow

```bash
git tag v0.1.0
git push origin v0.1.0
```

The tag will trigger a versioned Docker image build.

## Runtime safety and FNOS boundary

Optional API protection:

```yaml
environment:
  - EMBY_CLEAN_API_KEY=replace-with-a-long-random-value
```

When enabled, the browser UI can store the key locally in the settings page and
send it as `X-API-Key`. Do not expose the service directly to the public
internet.

The service only uses the Emby API and read-only media/source inspection. It
does not write MDC/NFO/image metadata or delete STRM/remote source files; an
explicitly confirmed Emby item may still be deleted through the Emby API.
Deletion is an explicit Emby-item action; the default is a dry-run plan.

New inspection modes include `image`, `media_health`, `strm_health`,
`source_dupe`, and `content_dupe`. A FUSE/115 path that is temporarily
unavailable is reported as unavailable and must not be treated as a missing or
deletable resource.
