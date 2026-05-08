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

    client = AsyncIOMotorClient(settings.mongo_uri)
    database = client[settings.mongo_db_name]
    await database.command("ping")
    await get_projects_collection().create_index("normalized_repo_url", unique=True)
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
