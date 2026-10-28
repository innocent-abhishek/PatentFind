import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from pymongo.errors import DuplicateKeyError, PyMongoError

from app.core.config import settings
from app.core.security import hash_password, validate_registration_input
from app.db.mongodb import db
from app.db.user_db import init_user_indexes

logger = logging.getLogger("patentfind.admin_setup")

SETUP_LOCK_ID = "initial_admin_setup_lock"


def setup_initial_admin(
    username: str,
    email: str,
    password: str,
    target_db=None
) -> Dict[str, Any]:
    """
    Safely creates the initial administrator account.
    
    Security & Concurrency Protections:
    1. Rejects execution if an administrator account already exists.
    2. Enforces atomic database-level concurrency protection by inserting a uniquely
       identified lock document (_id=SETUP_LOCK_ID) and handling DuplicateKeyError.
    3. Scopes lock release with a unique process lock_token: a process can ONLY release
       or update its own lock and will never delete another process's lock.
    4. Never promotes an existing user: rejects if username or email already exists.
    5. Hashes the password using bcrypt before storing.
    6. Leaves patent collections untouched.
    """
    database = target_db if target_db is not None else db
    users_col = database[settings.USERS_COLLECTION]
    locks_col = database[settings.APP_LOCKS_COLLECTION]

    # 1. Normalize and validate input
    clean_username, clean_email = validate_registration_input(username, email, password)

    # 2. Ensure unique user indexes exist
    init_user_indexes(target_db=database)

    # 3. Check if an admin already exists in the users collection
    if users_col.find_one({"role": "admin"}):
        raise RuntimeError(
            "An administrator account already exists in the database. "
            "Only one initial administrator can be created through this setup process."
        )

    # 4. Check that username or email does not collide with an existing regular user
    if users_col.find_one({"username": clean_username}):
        raise RuntimeError(
            f"User with username '{clean_username}' already exists. "
            "Setup script will not automatically promote an existing user."
        )
    if users_col.find_one({"email": clean_email}):
        raise RuntimeError(
            f"User with email '{clean_email}' already exists. "
            "Setup script will not automatically promote an existing user."
        )

    # 5. Database-level atomic concurrency lock:
    # Attempt atomic acquisition by inserting a uniquely identified lock document.
    # If the document already exists, MongoDB immediately raises DuplicateKeyError.
    lock_token = uuid.uuid4().hex
    now_iso = datetime.now(timezone.utc).isoformat()

    lock_doc = {
        "_id": SETUP_LOCK_ID,
        "status": "in_progress",
        "claimed_by": clean_username,
        "lock_token": lock_token,
        "locked_at": now_iso
    }

    try:
        locks_col.insert_one(lock_doc)
    except DuplicateKeyError:
        # A lock document already exists in the database
        if users_col.find_one({"role": "admin"}):
            raise RuntimeError(
                "An administrator account already exists. Setup refused."
            )
        raise RuntimeError(
            "Setup locked: Another administrator setup attempt is currently in progress or a previous "
            "attempt was interrupted. If an earlier setup failed, follow the documented recovery "
            "procedure (scripts/create_initial_admin.py --reset-lock) to safely clear the lock."
        )
    except PyMongoError as exc:
        logger.error("Database connection failure while acquiring setup lock: %s", exc)
        raise RuntimeError("A database error occurred while acquiring the setup lock.") from exc

    # 6. Exclusive lock acquired. Perform admin insertion safely.
    try:
        # Double-check inside locked section
        if users_col.find_one({"role": "admin"}):
            raise RuntimeError("An administrator account already exists. Setup refused.")

        hashed = hash_password(password)
        admin_doc = {
            "username": clean_username,
            "email": clean_email,
            "hashed_password": hashed,
            "role": "admin",
            "created_at": now_iso
        }

        insert_result = users_col.insert_one(admin_doc)

        # Mark lock as completed, strictly conditioned on this process's lock_token
        locks_col.update_one(
            {"_id": SETUP_LOCK_ID, "lock_token": lock_token},
            {"$set": {
                "status": "completed",
                "admin_id": str(insert_result.inserted_id),
                "completed_at": datetime.now(timezone.utc).isoformat()
            }}
        )

        logger.info("Successfully created initial administrator '%s'.", clean_username)
        return {
            "id": str(insert_result.inserted_id),
            "username": clean_username,
            "email": clean_email,
            "role": "admin",
            "created_at": now_iso
        }

    except DuplicateKeyError as exc:
        # Release only our lock so operator can retry with unique credentials
        locks_col.delete_one({"_id": SETUP_LOCK_ID, "lock_token": lock_token})
        raise RuntimeError(
            "Failed to create admin: A user with this username or email was created concurrently."
        ) from exc
    except Exception as exc:
        # Release only our lock on failure so operator is not locked out indefinitely
        locks_col.delete_one({"_id": SETUP_LOCK_ID, "lock_token": lock_token})
        if not isinstance(exc, RuntimeError):
            logger.error("Initial admin creation failed: %s", exc)
            raise RuntimeError("A database error occurred while creating the administrator.") from exc
        raise


def reset_setup_lock(
    target_db=None,
    stale_timeout_seconds: Optional[int] = None,
    force: bool = False
) -> bool:
    """
    Safely clears a stale setup lock from an interrupted setup attempt.

    Protections against race conditions:
    1. Refuses to clear if an administrator account already exists.
    2. Refuses to clear an 'in_progress' lock if it was acquired recently (within
       stale_timeout_seconds) unless force=True is explicitly specified. This prevents
       accidentally deleting an active lock belonging to a currently running setup process.
    3. Returns True if a lock was safely removed, False if no lock was present.
    """
    database = target_db if target_db is not None else db
    users_col = database[settings.USERS_COLLECTION]
    locks_col = database[settings.APP_LOCKS_COLLECTION]
    timeout = (
        stale_timeout_seconds
        if stale_timeout_seconds is not None
        else getattr(settings, "ADMIN_SETUP_LOCK_TIMEOUT_SECONDS", 300)
    )

    # 1. Protect existing administrator
    if users_col.find_one({"role": "admin"}):
        raise RuntimeError(
            "Cannot reset setup lock: An administrator account already exists in the database."
        )

    # 2. Check if a lock document exists
    lock_doc = locks_col.find_one({"_id": SETUP_LOCK_ID})
    if not lock_doc:
        return False

    # 3. Guard against deleting a potentially active lock
    if lock_doc.get("status") == "in_progress" and not force:
        locked_at_str = lock_doc.get("locked_at")
        if locked_at_str:
            try:
                locked_at_dt = datetime.fromisoformat(locked_at_str)
                if locked_at_dt.tzinfo is None:
                    locked_at_dt = locked_at_dt.replace(tzinfo=timezone.utc)
                age_seconds = (datetime.now(timezone.utc) - locked_at_dt).total_seconds()
                if age_seconds < timeout:
                    claimed_by = lock_doc.get("claimed_by", "another process")
                    raise RuntimeError(
                        f"Cannot reset lock: Setup lock was acquired only {int(age_seconds)}s ago by '{claimed_by}' "
                        f"and may belong to an active setup process. Wait until the {timeout}s timeout expires, "
                        "or specify force=True after verifying no setup process is running."
                    )
            except ValueError:
                pass

    res = locks_col.delete_one({"_id": SETUP_LOCK_ID})
    return res.deleted_count > 0
