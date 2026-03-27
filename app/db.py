import os

from pymongo import MongoClient
from pymongo.errors import ConfigurationError


DEFAULT_MONGO_URI = "mongodb://localhost:27017/mpraca"
DEFAULT_DB_NAME = "mpraca"


def _resolve_database(client, db_name):
    # Prefer DB name from URI. Fallback to explicit env DB name.
    try:
        default_db = client.get_default_database()
    except ConfigurationError:
        default_db = None

    if default_db is not None:
        return default_db

    return client[db_name]


def _ensure_indexes(database):
    database["cvs"].create_index("user_id", unique=True)
    database["applications"].create_index("employer_id")
    database["jobs"].create_index("required_skills")


def init_mongo():
    mongo_uri = os.getenv("MONGO_URI", DEFAULT_MONGO_URI)
    mongo_db_name = os.getenv("MONGO_DB_NAME", DEFAULT_DB_NAME)

    try:
        client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
        database = _resolve_database(client, mongo_db_name)

        # Fail fast on startup if DB connection is not reachable.
        client.admin.command("ping")
        _ensure_indexes(database)
        print(f"[DB] Connected to MongoDB database '{database.name}'")
    except Exception as exc:
        print(f"[DB] MongoDB connection failed: {exc}")
        raise

    return client, database
