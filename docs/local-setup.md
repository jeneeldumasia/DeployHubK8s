# Local Setup

## Prerequisites

- Docker Desktop
- Linux container mode enabled
- A public GitHub repository to test with

## Start DeployHub

```bash
docker compose up --build
```

## Local URLs

- Frontend: `http://localhost:3000`
- Backend API: `http://localhost:8000`
- MongoDB: `mongodb://localhost:27017`

## Environment Variables

Recommended local defaults:

```env
MONGO_URI=mongodb://mongo:27017/deployhub
MONGO_DB_NAME=deployhub
PUBLIC_BASE_URL=http://localhost
BACKEND_VERSION=2.0.0
PORT_RANGE_START=3001
PORT_RANGE_END=3999
CORS_ORIGINS=*
```

## Validation Steps

1. Open the frontend
2. Add a public repo URL
3. Deploy the project
4. Watch build logs move in real time
5. Open the generated service URL
6. Stop and redeploy the project
7. Delete the project and confirm resources are cleaned

## MongoDB Notes

- MongoDB runs automatically via Docker Compose
- No manual MongoDB installation is required
- Collections and indexes are auto-created by the backend on startup
