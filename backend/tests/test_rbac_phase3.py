from datetime import datetime, timezone, timedelta
import unittest
from unittest.mock import patch
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.core.security import create_access_token
from app.api.deps import get_current_user_claims, require_admin
from app.schemas.index import IndexBuildResponse


class TestRBACPhase3(unittest.TestCase):
    """
    Test suite for Phase 3: JWT authentication and admin-role authorization.
    Verifies that POST /api/index/build is protected while GET /status and GET /search remain public.
    """

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    # -------------------------------------------------------------------------
    # 1. Public Endpoints Verification
    # -------------------------------------------------------------------------
    def test_01_public_endpoints_accessible_without_token(self):
        """Verify that GET /api/index/status and GET /api/search remain public."""
        # GET /api/index/status requires no authentication
        status_res = self.client.get("/api/index/status")
        self.assertEqual(status_res.status_code, 200)

        # GET /api/search requires no authentication
        search_res = self.client.get("/api/search?q=solar")
        self.assertEqual(search_res.status_code, 200)

    # -------------------------------------------------------------------------
    # 2. POST /api/index/build Authentication & Authorization Checks
    # -------------------------------------------------------------------------
    def test_02_build_index_missing_token_returns_401(self):
        """Verify POST /api/index/build without token returns 401 Unauthorized."""
        res = self.client.post("/api/index/build")
        self.assertEqual(res.status_code, 401)
        self.assertIn("Not authenticated", res.json()["detail"])

    def test_03_build_index_invalid_token_returns_401(self):
        """Verify POST /api/index/build with a malformed/invalid token returns 401."""
        headers = {"Authorization": "Bearer this_is_a_completely_invalid_jwt_token"}
        res = self.client.post("/api/index/build", headers=headers)
        self.assertEqual(res.status_code, 401)
        self.assertIn("Invalid authentication token", res.json()["detail"])

    def test_04_build_index_expired_token_returns_401(self):
        """Verify POST /api/index/build with an expired token returns 401."""
        # Create an expired token (expired 10 seconds ago)
        expired_token = create_access_token(
            data={"sub": "123", "username": "admin_user", "role": "admin"},
            expires_delta=timedelta(seconds=-10)
        )
        headers = {"Authorization": f"Bearer {expired_token}"}
        res = self.client.post("/api/index/build", headers=headers)
        self.assertEqual(res.status_code, 401)
        self.assertIn("Token has expired", res.json()["detail"])

    def test_05_build_index_regular_user_token_returns_403(self):
        """Verify POST /api/index/build with regular user token (role='user') returns 403 Forbidden."""
        user_token = create_access_token(
            data={"sub": "456", "username": "regular_user", "role": "user"}
        )
        headers = {"Authorization": f"Bearer {user_token}"}
        res = self.client.post("/api/index/build", headers=headers)
        self.assertEqual(res.status_code, 403)
        self.assertIn("Administrator privileges required", res.json()["detail"])

    def test_06_build_index_admin_token_succeeds(self):
        """Verify POST /api/index/build with admin token (role='admin') succeeds (200 OK)."""
        admin_token = create_access_token(
            data={"sub": "789", "username": "super_admin", "role": "admin"}
        )
        headers = {"Authorization": f"Bearer {admin_token}"}

        # Mock build_inverted_index to avoid full re-indexing of 151k documents during test
        mock_response = IndexBuildResponse(
            success=True,
            status="ready",
            records_processed=151439,
            unique_terms_indexed=39550,
            total_postings=1384756,
            elapsed_time_seconds=1.23,
            message="Index built successfully."
        )

        with patch("app.api.routes.index.build_inverted_index", return_value=mock_response):
            res = self.client.post("/api/index/build", headers=headers)
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertTrue(data["success"])
            self.assertEqual(data["status"], "ready")

    # -------------------------------------------------------------------------
    # 3. Direct Dependency Function Tests
    # -------------------------------------------------------------------------
    def test_07_dependency_require_admin_logic(self):
        """Test require_admin dependency directly with user and admin claims."""
        # Non-admin claims
        user_claims = {"sub": "1", "username": "alice", "role": "user"}
        with self.assertRaises(HTTPException) as ctx:
            require_admin(user_claims)
        self.assertEqual(ctx.exception.status_code, 403)

        # Admin claims
        admin_claims = {"sub": "2", "username": "bob", "role": "admin"}
        result = require_admin(admin_claims)
        self.assertEqual(result["role"], "admin")
        self.assertEqual(result["username"], "bob")


if __name__ == "__main__":
    unittest.main()
