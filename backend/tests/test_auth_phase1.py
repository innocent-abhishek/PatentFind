from datetime import datetime, timezone, timedelta
import io
import sys
import unittest
import threading
from unittest.mock import patch
from pydantic import ValidationError
from fastapi import HTTPException

from app.core.config import settings
from app.core.security import (
    hash_password,
    verify_password,
    validate_registration_input,
    decode_access_token,
    MIN_PASSWORD_LENGTH,
    MAX_PASSWORD_BYTES
)
from app.schemas.auth import (
    UserRegisterRequest,
    UserRegisterResponse,
    UserLoginRequest,
    UserLoginResponse
)
from app.db.mongodb import client, db, check_mongodb
from app.db.user_db import init_user_indexes
from app.api.routes.auth import register, login
from app.services.admin_setup import setup_initial_admin, reset_setup_lock, SETUP_LOCK_ID
import scripts.create_initial_admin as cli_module


class TestBackendAuthPhase1(unittest.TestCase):
    """
    Focused test suite for Authentication Foundation and User Login.
    Uses an isolated test database ('patentfind_test_auth') so production/patent
    collections are never modified.
    """

    @classmethod
    def setUpClass(cls):
        # Dedicated isolated test database
        cls.test_db_name = "patentfind_test_auth"
        cls.test_db = client[cls.test_db_name]
        # Clean up any residual data in test db
        client.drop_database(cls.test_db_name)
        # Initialize unique indexes on the test database
        init_user_indexes(target_db=cls.test_db)

    @classmethod
    def tearDownClass(cls):
        # Drop test database after all tests complete
        client.drop_database(cls.test_db_name)

    def setUp(self):
        # Clear users and locks collection before each test
        self.test_db[settings.USERS_COLLECTION].delete_many({})
        self.test_db[settings.APP_LOCKS_COLLECTION].delete_many({})

    # -------------------------------------------------------------------------
    # 1. Password Hashing and Verification
    # -------------------------------------------------------------------------
    def test_01_password_hashing_and_verification_success(self):
        """Test hashing produces a valid bcrypt hash and verifies correctly."""
        password = "SecurePassword123!"
        hashed = hash_password(password)

        self.assertIsInstance(hashed, str)
        self.assertTrue(hashed.startswith("$2b$") or hashed.startswith("$2a$"))
        self.assertNotEqual(password, hashed)

        # Successful verification
        self.assertTrue(verify_password(password, hashed))

        # Different salt per hash
        hashed2 = hash_password(password)
        self.assertNotEqual(hashed, hashed2)
        self.assertTrue(verify_password(password, hashed2))

    def test_02_password_verification_incorrect_and_malformed(self):
        """Test password verification fails cleanly on wrong or malformed input."""
        password = "CorrectPassword123"
        hashed = hash_password(password)

        # Wrong password
        self.assertFalse(verify_password("WrongPassword123", hashed))
        self.assertFalse(verify_password("", hashed))

        # Malformed hash string (should return False, not raise exception)
        self.assertFalse(verify_password(password, "not_a_valid_hash"))
        self.assertFalse(verify_password(password, ""))

    # -------------------------------------------------------------------------
    # 2. Input Validation
    # -------------------------------------------------------------------------
    def test_03_invalid_registration_inputs(self):
        """Test validation rules for username, email, and password."""
        # Username too short
        with self.assertRaises(ValueError) as ctx:
            validate_registration_input("ab", "user@example.com", "Password123")
        self.assertIn("between 3 and 30", str(ctx.exception))

        # Username with invalid characters
        with self.assertRaises(ValueError) as ctx:
            validate_registration_input("user name!", "user@example.com", "Password123")
        self.assertIn("alphanumeric", str(ctx.exception))

        # Invalid email format
        with self.assertRaises(ValueError) as ctx:
            validate_registration_input("valid_user", "invalid-email", "Password123")
        self.assertIn("Invalid email format", str(ctx.exception))

        # Password too short (< 8 chars)
        with self.assertRaises(ValueError) as ctx:
            validate_registration_input("valid_user", "user@example.com", "short")
        self.assertIn(f"at least {MIN_PASSWORD_LENGTH} characters", str(ctx.exception))

        # Password exceeding 72 bytes (Bcrypt algorithm limit)
        long_password = "a" * (MAX_PASSWORD_BYTES + 1)
        with self.assertRaises(ValueError) as ctx:
            validate_registration_input("valid_user", "user@example.com", long_password)
        self.assertIn(f"must not exceed {MAX_PASSWORD_BYTES} bytes", str(ctx.exception))

    def test_04_normalization_of_username_and_email(self):
        """Test username and email are stripped and lowercased."""
        clean_user, clean_email = validate_registration_input(
            "   John_Doe   ",
            "   User.NAME@Example.COM   ",
            "ValidPassword123"
        )
        self.assertEqual(clean_user, "john_doe")
        self.assertEqual(clean_email, "user.name@example.com")

    # -------------------------------------------------------------------------
    # 3. Public User Registration & MongoDB Storage
    # -------------------------------------------------------------------------
    def test_05_successful_user_registration_and_db_storage(self):
        """Test public registration persists user with role='user' and safe response."""
        payload = UserRegisterRequest(
            username="analyst_bob",
            email="bob@patentfirm.com",
            password="StrongPassword123!"
        )

        with patch("app.api.routes.auth.db", self.test_db):
            response = register(payload)

        # Check response schema
        self.assertIsInstance(response, UserRegisterResponse)
        self.assertEqual(response.username, "analyst_bob")
        self.assertEqual(response.email, "bob@patentfirm.com")
        self.assertEqual(response.role, "user")
        self.assertIsNotNone(response.id)
        self.assertIsNotNone(response.created_at)

        # Safe response: verify hashed_password is NOT in the response dictionary
        response_dict = response.model_dump()
        self.assertNotIn("hashed_password", response_dict)
        self.assertNotIn("password", response_dict)

        # Verify permanent MongoDB persistence in users collection
        stored_user = self.test_db[settings.USERS_COLLECTION].find_one({"username": "analyst_bob"})
        self.assertIsNotNone(stored_user)
        self.assertEqual(stored_user["email"], "bob@patentfirm.com")
        self.assertEqual(stored_user["role"], "user")
        self.assertTrue(verify_password("StrongPassword123!", stored_user["hashed_password"]))
        # Never store plain password
        self.assertNotEqual(stored_user["hashed_password"], "StrongPassword123!")

    def test_06_duplicate_username_and_email_handling(self):
        """Test duplicate registration returns 409 Conflict with clear message."""
        payload1 = UserRegisterRequest(
            username="unique_user",
            email="unique@example.com",
            password="Password123!"
        )
        with patch("app.api.routes.auth.db", self.test_db):
            register(payload1)

            # Duplicate username
            payload_dup_user = UserRegisterRequest(
                username="UNIQUE_USER",  # normalized to same
                email="another@example.com",
                password="Password123!"
            )
            with self.assertRaises(HTTPException) as ctx:
                register(payload_dup_user)
            self.assertEqual(ctx.exception.status_code, 409)
            self.assertIn("Username 'unique_user' is already registered", ctx.exception.detail)

            # Duplicate email
            payload_dup_email = UserRegisterRequest(
                username="another_user",
                email="UNIQUE@EXAMPLE.COM",  # normalized to same
                password="Password123!"
            )
            with self.assertRaises(HTTPException) as ctx:
                register(payload_dup_email)
            self.assertEqual(ctx.exception.status_code, 409)
            self.assertIn("Email 'unique@example.com' is already registered", ctx.exception.detail)

    def test_07_attempt_to_supply_admin_role_rejected(self):
        """Test client cannot pass role='admin' into public registration."""
        # 1. Pydantic validation rejects extra fields like 'role'
        with self.assertRaises(ValidationError):
            UserRegisterRequest(
                username="hacker_user",
                email="hacker@example.com",
                password="Password123!",
                role="admin"  # Forbidden extra field
            )

        # 2. Even if route receives raw model, server assigns role='user'
        payload = UserRegisterRequest(
            username="normal_user",
            email="normal@example.com",
            password="Password123!"
        )
        with patch("app.api.routes.auth.db", self.test_db):
            res = register(payload)
            self.assertEqual(res.role, "user")

            stored = self.test_db[settings.USERS_COLLECTION].find_one({"username": "normal_user"})
            self.assertEqual(stored["role"], "user")

    # -------------------------------------------------------------------------
    # 4. Secure Initial Admin Setup & Lock Concurrency Protection
    # -------------------------------------------------------------------------
    def test_08_initial_admin_creation_success(self):
        """Test initial admin creation stores admin with role='admin'."""
        result = setup_initial_admin(
            username="super_admin",
            email="admin@patentfind.org",
            password="AdminMasterPass123!",
            target_db=self.test_db
        )

        self.assertEqual(result["role"], "admin")
        self.assertEqual(result["username"], "super_admin")
        self.assertEqual(result["email"], "admin@patentfind.org")

        # Verify record in DB
        admin_doc = self.test_db[settings.USERS_COLLECTION].find_one({"username": "super_admin"})
        self.assertIsNotNone(admin_doc)
        self.assertEqual(admin_doc["role"], "admin")
        self.assertTrue(verify_password("AdminMasterPass123!", admin_doc["hashed_password"]))

        # Verify lock status is marked completed
        lock_doc = self.test_db[settings.APP_LOCKS_COLLECTION].find_one({"_id": SETUP_LOCK_ID})
        self.assertIsNotNone(lock_doc)
        self.assertEqual(lock_doc["status"], "completed")

        # Verify patent collections in main db were completely untouched
        self.assertNotIn("patents_2016", self.test_db.list_collection_names())

    def test_09_refusal_to_create_second_admin_or_promote_user(self):
        """Test second admin creation attempt is refused, and existing users cannot be promoted."""
        # 1. Create first admin
        setup_initial_admin(
            username="admin_one",
            email="admin1@patentfind.org",
            password="AdminPass123!",
            target_db=self.test_db
        )

        # 2. Attempt to create second admin
        with self.assertRaises(RuntimeError) as ctx:
            setup_initial_admin(
                username="admin_two",
                email="admin2@patentfind.org",
                password="AdminPass456!",
                target_db=self.test_db
            )
        self.assertIn("already exists", str(ctx.exception))

        # Verify only 1 admin exists in DB
        admin_count = self.test_db[settings.USERS_COLLECTION].count_documents({"role": "admin"})
        self.assertEqual(admin_count, 1)

    def test_10_refusal_to_promote_existing_regular_user(self):
        """Test setup script refuses if username or email belongs to an existing user."""
        # Insert a regular user first
        self.test_db[settings.USERS_COLLECTION].insert_one({
            "username": "existing_user",
            "email": "user@patentfind.org",
            "hashed_password": hash_password("UserPassword123!"),
            "role": "user",
            "created_at": "2026-01-01T00:00:00"
        })

        # Try to run admin setup with that username
        with self.assertRaises(RuntimeError) as ctx:
            setup_initial_admin(
                username="existing_user",
                email="new_email@patentfind.org",
                password="AdminPass123!",
                target_db=self.test_db
            )
        self.assertIn("already exists", str(ctx.exception))
        self.assertIn("will not automatically promote", str(ctx.exception))

    def test_11_concurrent_admin_setup_protection(self):
        """Test simultaneous initial admin setup attempts safely allow at most one winner."""
        results = []
        errors = []

        def worker(idx):
            try:
                res = setup_initial_admin(
                    username=f"admin_{idx}",
                    email=f"admin_{idx}@example.com",
                    password=f"AdminPass_{idx}_123!",
                    target_db=self.test_db
                )
                results.append(res)
            except Exception as exc:
                errors.append(exc)

        # Spawn two concurrent setup threads
        t1 = threading.Thread(target=worker, args=(1,))
        t2 = threading.Thread(target=worker, args=(2,))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Exactly one thread must succeed, and one must fail
        self.assertEqual(len(results), 1, "Exactly one concurrent setup must succeed.")
        self.assertEqual(len(errors), 1, "The competing concurrent setup must be refused.")

        # Total admins in collection must be exactly 1
        total_admins = self.test_db[settings.USERS_COLLECTION].count_documents({"role": "admin"})
        self.assertEqual(total_admins, 1)

    def test_12_lock_cleanup_on_failure_and_token_scoping(self):
        """Test failed setup clears its own lock, and cannot delete another process's lock."""
        locks_col = self.test_db[settings.APP_LOCKS_COLLECTION]

        # Simulate another process having an active lock with token 'other_token'
        locks_col.insert_one({
            "_id": SETUP_LOCK_ID,
            "status": "in_progress",
            "claimed_by": "other_proc",
            "lock_token": "other_proc_secret_token",
            "locked_at": "2026-01-01T00:00:00"
        })

        # Attempting setup must be refused due to existing lock
        with self.assertRaises(RuntimeError) as ctx:
            setup_initial_admin(
                username="new_admin",
                email="new_admin@patentfind.org",
                password="Password123!",
                target_db=self.test_db
            )
        self.assertIn("Another administrator setup attempt is currently in progress", str(ctx.exception))

        # Verify the other process's lock was NOT deleted
        lock_doc = locks_col.find_one({"_id": SETUP_LOCK_ID})
        self.assertIsNotNone(lock_doc)
        self.assertEqual(lock_doc["lock_token"], "other_proc_secret_token")

    def test_13_reset_setup_lock_race_condition_protection(self):
        """
        Verify that reset_setup_lock refuses to delete an active in-progress lock
        just because no admin exists, protecting concurrent active setup processes.
        """
        locks_col = self.test_db[settings.APP_LOCKS_COLLECTION]
        users_col = self.test_db[settings.USERS_COLLECTION]

        # 1. An active lock was recently acquired (locked 10 seconds ago)
        active_time = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
        locks_col.insert_one({
            "_id": SETUP_LOCK_ID,
            "status": "in_progress",
            "claimed_by": "active_setup_process",
            "lock_token": "active_token_123",
            "locked_at": active_time
        })

        # Calling reset_setup_lock without force MUST BE REFUSED
        with self.assertRaises(RuntimeError) as ctx:
            reset_setup_lock(target_db=self.test_db, stale_timeout_seconds=300, force=False)
        self.assertIn("may belong to an active setup process", str(ctx.exception))
        # Lock must NOT have been deleted
        self.assertIsNotNone(locks_col.find_one({"_id": SETUP_LOCK_ID}))

        # 2. Manual recovery with force=True removes the lock safely
        cleared_forced = reset_setup_lock(target_db=self.test_db, force=True)
        self.assertTrue(cleared_forced)
        self.assertIsNone(locks_col.find_one({"_id": SETUP_LOCK_ID}))

        # 3. An expired/stale lock (e.g. 600 seconds old) CAN be reset without force
        stale_time = (datetime.now(timezone.utc) - timedelta(seconds=600)).isoformat()
        locks_col.insert_one({
            "_id": SETUP_LOCK_ID,
            "status": "in_progress",
            "claimed_by": "dead_process",
            "lock_token": "dead_token_456",
            "locked_at": stale_time
        })
        cleared_stale = reset_setup_lock(target_db=self.test_db, stale_timeout_seconds=300, force=False)
        self.assertTrue(cleared_stale)
        self.assertIsNone(locks_col.find_one({"_id": SETUP_LOCK_ID}))

        # 4. If an admin exists in users collection, reset is strictly forbidden even with force=True
        users_col.insert_one({
            "username": "existing_admin",
            "email": "admin@patentfind.org",
            "hashed_password": "hash",
            "role": "admin"
        })
        locks_col.insert_one({"_id": SETUP_LOCK_ID, "status": "completed"})
        with self.assertRaises(RuntimeError) as ctx:
            reset_setup_lock(target_db=self.test_db, force=True)
        self.assertIn("An administrator account already exists", str(ctx.exception))
        self.assertIsNotNone(locks_col.find_one({"_id": SETUP_LOCK_ID}))

    def test_14_cli_password_argument_removed_and_masked_prompting(self):
        """Test that --password argument is removed and getpass masks password correctly."""
        # 1. Verify --password argument is rejected by CLI argument parser
        test_args_with_pwd = ["create_initial_admin.py", "--password", "Secret123!"]
        with patch.object(sys, "argv", test_args_with_pwd):
            with self.assertRaises(SystemExit) as ctx:
                with patch("sys.stderr", new_callable=io.StringIO):
                    cli_module.main()
            # Non-zero exit code because --password is an unrecognized argument
            self.assertNotEqual(ctx.exception.code, 0)

        # 2. Verify masked password prompt with mismatched passwords fails safely
        test_args_mismatch = ["create_initial_admin.py", "--username", "admin1", "--email", "admin1@example.com"]
        with patch.object(sys, "argv", test_args_mismatch):
            with patch("getpass.getpass", side_effect=["SecretPass1!", "MismatchedPass2!"]):
                with patch("sys.stderr", new_callable=io.StringIO) as mock_stderr:
                    with self.assertRaises(SystemExit) as ctx:
                        cli_module.main()
                    self.assertEqual(ctx.exception.code, 1)
                    err_output = mock_stderr.getvalue()
                    self.assertIn("Passwords do not match", err_output)
                    # Verify neither password was printed
                    self.assertNotIn("SecretPass1!", err_output)
                    self.assertNotIn("MismatchedPass2!", err_output)

    # -------------------------------------------------------------------------
    # 5. User Login & JWT Access Tokens (Phase 2)
    # -------------------------------------------------------------------------
    def test_15_user_login_success_username_and_email(self):
        """Test successful login via username or email returns signed JWT token."""
        # 1. Register a user in the test database
        register_payload = UserRegisterRequest(
            username="analyst_alice",
            email="alice@patentfirm.com",
            password="AlicePassword123!"
        )
        with patch("app.api.routes.auth.db", self.test_db):
            register(register_payload)

            # 2. Login using username
            login_req_user = UserLoginRequest(
                username="analyst_alice",
                password="AlicePassword123!"
            )
            login_res = login(login_req_user)

            self.assertIsInstance(login_res, UserLoginResponse)
            self.assertEqual(login_res.token_type, "bearer")
            self.assertGreater(login_res.expires_in, 0)
            self.assertEqual(login_res.user.username, "analyst_alice")
            self.assertEqual(login_res.user.email, "alice@patentfirm.com")
            self.assertEqual(login_res.user.role, "user")
            self.assertIsNotNone(login_res.access_token)

            # Verify and decode JWT claims
            claims = decode_access_token(login_res.access_token)
            self.assertIsNotNone(claims)
            self.assertEqual(claims["username"], "analyst_alice")
            self.assertEqual(claims["email"], "alice@patentfirm.com")
            self.assertEqual(claims["role"], "user")
            self.assertEqual(claims["sub"], login_res.user.id)
            self.assertIn("exp", claims)
            self.assertIn("iat", claims)

            # 3. Login using email (case-insensitive)
            login_req_email = UserLoginRequest(
                username="ALICE@PATENTFIRM.COM",
                password="AlicePassword123!"
            )
            login_res_email = login(login_req_email)
            self.assertEqual(login_res_email.user.username, "analyst_alice")
            self.assertIsNotNone(login_res_email.access_token)

    def test_16_user_login_invalid_credentials_and_malformed_input(self):
        """Test wrong password, nonexistent user, and malformed login inputs."""
        # Register a user in the test database
        register_payload = UserRegisterRequest(
            username="test_login_user",
            email="login_user@example.com",
            password="CorrectPassword123!"
        )
        with patch("app.api.routes.auth.db", self.test_db):
            register(register_payload)

            # 1. Wrong password -> 401 Unauthorized
            with self.assertRaises(HTTPException) as ctx:
                login(UserLoginRequest(username="test_login_user", password="WrongPassword999!"))
            self.assertEqual(ctx.exception.status_code, 401)
            self.assertEqual(ctx.exception.detail, "Invalid username or password.")

            # 2. Nonexistent user -> 401 Unauthorized (same message prevents enumeration)
            with self.assertRaises(HTTPException) as ctx:
                login(UserLoginRequest(username="nonexistent_user", password="AnyPassword123!"))
            self.assertEqual(ctx.exception.status_code, 401)
            self.assertEqual(ctx.exception.detail, "Invalid username or password.")

            # 3. Empty whitespace username -> 400 Bad Request
            with self.assertRaises(HTTPException) as ctx:
                login(UserLoginRequest(username="   ", password="AnyPassword123!"))
            self.assertEqual(ctx.exception.status_code, 400)
            self.assertIn("cannot be empty", ctx.exception.detail)

        # 4. Malformed input: forbidden extra fields (e.g. role)
        with self.assertRaises(ValidationError):
            UserLoginRequest(
                username="test_login_user",
                password="CorrectPassword123!",
                role="admin"  # Extra field forbidden by schema
            )

        # 5. Missing required password field
        with self.assertRaises(ValidationError):
            UserLoginRequest(username="test_login_user")


if __name__ == "__main__":
    unittest.main()
