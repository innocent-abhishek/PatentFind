import logging
from typing import Any, Dict, Optional
from pymongo.errors import DuplicateKeyError, OperationFailure

from app.core.config import settings
from app.db.mongodb import db

logger = logging.getLogger("patentfind.db.users")


def init_user_indexes(target_db=None) -> Dict[str, Any]:
    """
    Initializes unique indexes for the users collection in MongoDB:
    - 'unique_username': Enforces unique usernames.
    - 'unique_email': Enforces unique emails.

    Safety:
    - If duplicate data already exists in the collection, PyMongo raises OperationFailure.
    - This function clearly catches and reports the issue without deleting any records.
    - Reuses the existing MongoDB connection.
    """
    database = target_db if target_db is not None else db
    users_col = database[settings.USERS_COLLECTION]
    results = {}

    try:
        # Check existing indexes
        existing_indexes = users_col.index_information()

        # 1. Unique index on username
        if "unique_username" not in existing_indexes:
            idx_name = users_col.create_index("username", unique=True, name="unique_username")
            results["username_index"] = idx_name
            logger.info("Created unique index 'unique_username' on collection '%s'.", settings.USERS_COLLECTION)
        else:
            results["username_index"] = "already_exists"

        # 2. Unique index on email
        if "unique_email" not in existing_indexes:
            idx_name = users_col.create_index("email", unique=True, name="unique_email")
            results["email_index"] = idx_name
            logger.info("Created unique index 'unique_email' on collection '%s'.", settings.USERS_COLLECTION)
        else:
            results["email_index"] = "already_exists"

        return results

    except (DuplicateKeyError, OperationFailure) as exc:
        err_msg = (
            f"Failed to create unique indexes on '{settings.USERS_COLLECTION}' collection: {exc}. "
            "Existing records contain duplicate usernames or emails. "
            "Please resolve duplicate records manually. No records were deleted."
        )
        logger.error(err_msg)
        raise RuntimeError(err_msg) from exc
