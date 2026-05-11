# Deployment

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

It builds and pushes a multi-platform image to Docker Hub when:

- code is pushed to `main`
- a tag like `v1.0.0` is pushed
- the workflow is run manually

## Required GitHub Secrets

Create these repository secrets in GitHub:

- `DOCKERHUB_USERNAME`
- `DOCKERHUB_TOKEN`

The token should be a Docker Hub access token, not your Docker Hub account password.

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

