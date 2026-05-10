# Troubleshooting

## Docker Is Unavailable

Symptoms:
- builds fail immediately
- `/api/system` reports `docker_available: false`

Checks:
- make sure Docker Desktop is running
- verify Linux containers are enabled
- verify `/var/run/docker.sock` is mounted into the backend container

## MongoDB Is Unavailable

Symptoms:
- backend fails readiness
- project creation fails

Checks:
- run `docker compose ps`
- verify the `mongo` service is healthy
- verify `MONGO_URI=mongodb://mongo:27017/deployhub`

## Repo Clone Failure

Symptoms:
- project moves to `failed`
- build logs stop at clone

Causes:
- invalid repository URL
- repository is private
- unsupported host

## Build Failure

Symptoms:
- project moves to `failed`
- Docker build logs contain the error

Common causes:
- missing dependencies
- broken repo Dockerfile
- unsupported generated start command
- monorepo layout without a custom Dockerfile

## Container Exits Immediately

Symptoms:
- build succeeds but project becomes `failed`
- runtime logs contain startup crash details

Checks:
- inspect the runtime logs panel
- verify the repository actually binds to `0.0.0.0`
- provide a custom Dockerfile for complex startup behavior

## Port Allocation Failure

Symptoms:
- deploy fails while starting the container

Fix:
- widen `PORT_RANGE_START` and `PORT_RANGE_END`
- stop old project containers

## SSE Log Stream Drops

Symptoms:
- live stream status falls back to polling

Notes:
- the frontend automatically falls back to polling
- manual `Refresh Logs` still works
