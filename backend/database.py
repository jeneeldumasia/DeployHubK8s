from datetime import datetime, timezone
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection, AsyncIOMotorDatabase

from config import settings

client: AsyncIOMotorClient | None = None
database: AsyncIOMotorDatabase | None = None


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def connect_to_mongo() -> None:
    global client, database
    if client is not None:
        return

    client = AsyncIOMotorClient(settings.resolved_mongo_uri)
    database = client[settings.mongo_db_name]
    await database.command("ping")

    # Compound unique index — prevents duplicate (repo + context_path) pairs.
    # Drop the old single-field index if it exists (idempotent).
    try:
        await get_projects_collection().drop_index("normalized_repo_url_1")
    except Exception:
        pass

    # Before creating the unique index, remove any duplicate documents that
    # would violate it (keep the most recently updated one).
    try:
        pipeline = [
            {"$sort": {"updated_at": -1}},
            {"$group": {
                "_id": {"url": "$normalized_repo_url", "path": "$context_path"},
                "keep": {"$first": "$_id"},
                "dupes": {"$push": "$_id"},
            }},
            {"$project": {
                "dupes": {
                    "$filter": {
                        "input": "$dupes",
                        "cond": {"$ne": ["$$this", "$keep"]},
                    }
                }
            }},
        ]
        async for doc in get_projects_collection().aggregate(pipeline):
            if doc.get("dupes"):
                await get_projects_collection().delete_many({"_id": {"$in": doc["dupes"]}})
    except Exception:
        pass  # best-effort dedup; index creation may still fail on edge cases

    await get_projects_collection().create_index(
        [("normalized_repo_url", 1), ("context_path", 1)],
        unique=True,
    )
    await get_projects_collection().create_index("status")
    await get_projects_collection().create_index("created_at")
    await get_projects_collection().create_index("updated_at")


async def close_mongo_connection() -> None:
    global client, database
    if client is not None:
        client.close()
    client = None
    database = None


def get_database() -> AsyncIOMotorDatabase:
    if database is None:
        raise RuntimeError("MongoDB has not been initialized")
    return database


def get_projects_collection() -> AsyncIOMotorCollection:
    return get_database()["projects"]


def get_object_id(project_id: str):
    from bson import ObjectId
    if not ObjectId.is_valid(project_id):
        return None
    return ObjectId(project_id)


async def create_project(document: dict[str, Any]) -> str:
    result = await get_projects_collection().insert_one(document)
    return str(result.inserted_id)


async def get_project_by_id(project_id: str) -> dict[str, Any] | None:
    object_id = get_object_id(project_id)
    if object_id is None:
        return None
    return await get_projects_collection().find_one({"_id": object_id})


async def get_project_by_url_and_path(normalized_repo_url: str, context_path: str) -> dict[str, Any] | None:
    return await get_projects_collection().find_one(
        {"normalized_repo_url": normalized_repo_url, "context_path": context_path}
    )


async def get_project_by_normalized_repo_url(normalized_repo_url: str) -> dict[str, Any] | None:
    return await get_projects_collection().find_one({"normalized_repo_url": normalized_repo_url})


async def update_project(project_id: str, updates: dict[str, Any]) -> None:
    object_id = get_object_id(project_id)
    if object_id is None:
        raise ValueError("Invalid project id")
    updates["updated_at"] = utc_now()
    await get_projects_collection().update_one({"_id": object_id}, {"$set": updates})


async def append_build_log(project_id: str, line: str) -> None:
    object_id = get_object_id(project_id)
    if object_id is None:
        raise ValueError("Invalid project id")
    await get_projects_collection().update_one(
        {"_id": object_id},
        {"$push": {"build_logs": line}, "$set": {"updated_at": utc_now()}},
    )


async def append_deployment_history(project_id: str, entry: dict[str, Any]) -> None:
    """Push a deployment record into the project's history array."""
    object_id = get_object_id(project_id)
    if object_id is None:
        raise ValueError("Invalid project id")
    await get_projects_collection().update_one(
        {"_id": object_id},
        {
            "$push": {
                "deployment_history": {
                    "$each": [entry],
                    "$slice": -50,   # keep last 50 deployments
                }
            },
            "$set": {"updated_at": utc_now()},
        },
    )


async def list_projects() -> list[dict[str, Any]]:
    cursor = get_projects_collection().find().sort("created_at", -1)
    return await cursor.to_list(length=200)


async def delete_project(project_id: str) -> bool:
    object_id = get_object_id(project_id)
    if object_id is None:
        return False
    result = await get_projects_collection().delete_one({"_id": object_id})
    return result.deleted_count == 1


async def count_projects() -> int:
    return await get_projects_collection().count_documents({})


async def count_projects_by_status(status: str) -> int:
    return await get_projects_collection().count_documents({"status": status})


async def get_deployment_stats() -> dict[str, Any]:
    """
    Aggregate persistent deployment stats from MongoDB deployment_history arrays.
    These survive pod restarts unlike Prometheus counters.
    """
    pipeline = [
        {"$unwind": {"path": "$deployment_history", "preserveNullAndEmptyArrays": False}},
        {"$group": {
            "_id": None,
            "total":        {"$sum": 1},
            "successful":   {"$sum": {"$cond": [{"$eq": ["$deployment_history.status", "success"]}, 1, 0]}},
            "failed":       {"$sum": {"$cond": [{"$eq": ["$deployment_history.status", "failed"]}, 1, 0]}},
            "rolled_back":  {"$sum": {"$cond": [{"$eq": ["$deployment_history.status", "rolled_back"]}, 1, 0]}},
            "avg_duration": {"$avg": "$deployment_history.duration_seconds"},
        }},
    ]
    results = await get_projects_collection().aggregate(pipeline).to_list(length=1)
    if not results:
        return {"total": 0, "successful": 0, "failed": 0, "rolled_back": 0, "avg_duration_seconds": None}
    r = results[0]
    return {
        "total":                  r.get("total", 0),
        "successful":             r.get("successful", 0),
        "failed":                 r.get("failed", 0),
        "rolled_back":            r.get("rolled_back", 0),
        "avg_duration_seconds":   round(r["avg_duration"], 1) if r.get("avg_duration") else None,
    }
