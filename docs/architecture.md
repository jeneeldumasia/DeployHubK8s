# Architecture

DeployHub is a local deployment platform built around three long-lived services and a set of short-lived project containers.

## Components

- `frontend`: React UI served by Nginx
- `backend`: FastAPI API, system endpoints, metrics, and deployment worker
- `mongo`: MongoDB for project state and build logs
- project containers: real Docker containers launched from user repositories

## Core Data Flow

1. A user submits a public GitHub repository URL.
2. FastAPI validates and stores the project in MongoDB.
3. A deploy or redeploy request marks the project `queued`.
4. The in-process worker moves the project to `building`.
5. The worker clones or updates the repository.
6. DeployHub detects the project type and chooses a repo Dockerfile or generates one.
7. Docker builds a real image and starts a real container.
8. MongoDB stores the latest status, URL, logs, container metadata, and timestamps.
9. The frontend reads project state and streams logs through SSE.

## Storage Layout

- `/data/repos/<project_id>`: cloned repository
- `/data/generated-dockerfiles/<project_id>`: generated Dockerfile when needed
- MongoDB `projects` collection: lifecycle state and build logs

## Runtime Boundaries

- The backend uses a mounted Docker socket to control the host daemon.
- MongoDB runs locally in Docker Compose by default.
- Project builds and runtime logs are always real Docker outputs.

## Observability

- `/health` and `/ready`
- `/api/system`
- `/metrics`
- structured JSON backend logs for major lifecycle events
