# Deployment Flow

## Status Lifecycle

- `created`
- `queued`
- `building`
- `running`
- `stopped`
- `failed`
- `deleting`

## Deploy

1. `POST /api/deploy/{id}` or `POST /api/redeploy/{id}` sets the project to `queued`.
2. The worker starts and marks it `building`.
3. Git clone or pull runs for the repository.
4. Project type detection selects `node`, `python`, `static`, or `unknown`.
5. DeployHub uses an existing repo `Dockerfile` or generates one.
6. Docker builds the image using a deterministic tag: `deployhub-<project_id>:latest`
7. Any stale container named `deployhub-<project_id>` is removed before the new run.
8. A host port is allocated from the configured port range.
9. Docker runs the container with a deterministic name: `deployhub-<project_id>`
10. If the container stays alive, the project becomes `running`.
11. If any phase fails, the project becomes `failed` and `last_error` is updated.

## Stop

1. `POST /api/stop/{id}`
2. The backend removes the running container if present.
3. Project status becomes `stopped`
4. Build logs stay available for inspection

## Delete

1. `DELETE /api/projects/{id}`
2. Status becomes `deleting`
3. Container is removed if present
4. Image is removed if present
5. Local repo clone is deleted
6. Generated Dockerfile directory is deleted
7. MongoDB record is deleted

## Logs

- Build logs are persisted in MongoDB with timestamps
- Runtime logs are fetched directly from `docker logs`
- `GET /api/logs/{id}` returns a snapshot
- `GET /api/logs/{id}/stream` sends live SSE updates
