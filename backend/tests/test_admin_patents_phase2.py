import unittest
from datetime import timedelta
from unittest.mock import patch
from bson import ObjectId
from fastapi.testclient import TestClient
from pymongo import MongoClient

from app.main import app
from app.core.config import settings
from app.core.security import create_access_token

TEST_DB_NAME = "patentfind_test_admin_phase2"


class TestAdminPatentsPhase2(unittest.TestCase):
    """
    Test suite for Phase 2: Admin Patent CRUD operations and RBAC protection.
    Uses an isolated test database (patentfind_test_admin_phase2) to ensure
    production-like data in 'patentfind' is never modified.
    """

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.mongo_client = MongoClient(settings.MONGODB_URL, serverSelectionTimeoutMS=5000)
        cls.test_db = cls.mongo_client[TEST_DB_NAME]

        # Auth tokens
        cls.admin_token = create_access_token(
            data={"sub": "101", "username": "admin_tester", "role": "admin"}
        )
        cls.admin_headers = {"Authorization": f"Bearer {cls.admin_token}"}

        cls.user_token = create_access_token(
            data={"sub": "202", "username": "regular_tester", "role": "user"}
        )
        cls.user_headers = {"Authorization": f"Bearer {cls.user_token}"}

        cls.expired_token = create_access_token(
            data={"sub": "303", "username": "expired_admin", "role": "admin"},
            expires_delta=timedelta(seconds=-10)
        )
        cls.expired_headers = {"Authorization": f"Bearer {cls.expired_token}"}

        # Start db patch for admin_patent_service
        cls.db_patcher = patch("app.services.admin_patent_service.db", cls.test_db)
        cls.db_patcher.start()

    @classmethod
    def tearDownClass(cls):
        cls.db_patcher.stop()
        cls.mongo_client.drop_database(TEST_DB_NAME)
        cls.mongo_client.close()

    def setUp(self):
        # Clean collections in the isolated test database before each test
        for year in settings.PATENT_YEARS:
            self.test_db[f"patents_{year}"].delete_many({})

    # -------------------------------------------------------------------------
    # 1. RBAC & Authentication Enforcement (401 & 403)
    # -------------------------------------------------------------------------
    def test_01_unauthenticated_requests_return_401(self):
        """All /api/admin/patents endpoints must reject unauthenticated requests with 401."""
        dummy_id = str(ObjectId())

        # GET list
        res = self.client.get("/api/admin/patents")
        self.assertEqual(res.status_code, 401)
        self.assertIn("Not authenticated", res.json()["detail"])

        # GET detail
        res = self.client.get(f"/api/admin/patents/{dummy_id}")
        self.assertEqual(res.status_code, 401)

        # POST create
        res = self.client.post("/api/admin/patents", json={"application_number": "123"})
        self.assertEqual(res.status_code, 401)

        # PUT update
        res = self.client.put(f"/api/admin/patents/{dummy_id}", json={"title_of_invention": "New"})
        self.assertEqual(res.status_code, 401)

        # DELETE
        res = self.client.delete(f"/api/admin/patents/{dummy_id}")
        self.assertEqual(res.status_code, 401)

    def test_02_expired_and_invalid_token_returns_401(self):
        """Requests with expired or invalid tokens must receive 401."""
        # Expired token
        res = self.client.get("/api/admin/patents", headers=self.expired_headers)
        self.assertEqual(res.status_code, 401)
        self.assertIn("Token has expired", res.json()["detail"])

        # Malformed token
        res = self.client.get("/api/admin/patents", headers={"Authorization": "Bearer bad_token_123"})
        self.assertEqual(res.status_code, 401)
        self.assertIn("Invalid authentication token", res.json()["detail"])

    def test_03_regular_user_token_returns_403(self):
        """Regular users (role='user') must receive 403 Forbidden on all admin endpoints."""
        dummy_id = str(ObjectId())

        res = self.client.get("/api/admin/patents", headers=self.user_headers)
        self.assertEqual(res.status_code, 403)
        self.assertIn("Administrator privileges required", res.json()["detail"])

        res = self.client.get(f"/api/admin/patents/{dummy_id}", headers=self.user_headers)
        self.assertEqual(res.status_code, 403)

        res = self.client.post(
            "/api/admin/patents",
            headers=self.user_headers,
            json={"application_number": "TEST/01"}
        )
        self.assertEqual(res.status_code, 403)

        res = self.client.put(
            f"/api/admin/patents/{dummy_id}",
            headers=self.user_headers,
            json={"title_of_invention": "Forbidden Update"}
        )
        self.assertEqual(res.status_code, 403)

        res = self.client.delete(f"/api/admin/patents/{dummy_id}", headers=self.user_headers)
        self.assertEqual(res.status_code, 403)

    # -------------------------------------------------------------------------
    # 2. Input Validation Tests
    # -------------------------------------------------------------------------
    def test_04_create_patent_missing_required_fields(self):
        """Creating a patent missing required fields must fail with 422 Unprocessable Entity."""
        # Missing title_of_invention and publication_date
        res = self.client.post(
            "/api/admin/patents",
            headers=self.admin_headers,
            json={"application_number": "100/DEL/2023"}
        )
        self.assertEqual(res.status_code, 422)

    def test_05_create_patent_invalid_date_format(self):
        """Invalid date format must be rejected."""
        payload = {
            "application_number": "100/DEL/2023",
            "title_of_invention": "Test Patent",
            "publication_date": "2023-01-01"  # Not DD/MM/YYYY
        }
        res = self.client.post("/api/admin/patents", headers=self.admin_headers, json=payload)
        self.assertEqual(res.status_code, 422)

    def test_06_create_patent_unsupported_year_rejected(self):
        """Publication dates with years outside supported collections (2016-2023) must be rejected."""
        payload = {
            "application_number": "100/DEL/2025",
            "title_of_invention": "Future Patent",
            "publication_date": "01/01/2025"  # 2025 is outside 2016-2023
        }
        res = self.client.post("/api/admin/patents", headers=self.admin_headers, json=payload)
        self.assertEqual(res.status_code, 400)
        self.assertIn("Publication year '2025' is not supported", res.json()["detail"])

    def test_07_invalid_object_id_rejected(self):
        """Invalid ObjectId formats must return 400 Bad Request."""
        res = self.client.get("/api/admin/patents/not-a-valid-id", headers=self.admin_headers)
        self.assertEqual(res.status_code, 400)
        self.assertIn("Invalid patent ID format", res.json()["detail"])

    # -------------------------------------------------------------------------
    # 3. Create & Duplicate Detection Tests
    # -------------------------------------------------------------------------
    def test_08_create_patent_success(self):
        """Admin can successfully create a new patent record."""
        payload = {
            "application_number": "9999/DELNP/2023",
            "title_of_invention": "INNOVATIVE SOLAR PANEL COATING",
            "publication_date": "15/08/2023",
            "publication_number": "33/2023",
            "date_of_filing": "10/01/2022",
            "ipo_location": "Delhi",
            "application_type_desc": "ORDINARY APPLICATION",
            "field_of_invention": "ELECTRICAL",
            "no_of_pages": 32,
            "no_of_claims": 14
        }
        res = self.client.post("/api/admin/patents", headers=self.admin_headers, json=payload)
        self.assertEqual(res.status_code, 201)
        data = res.json()

        self.assertIsNotNone(data["id"])
        self.assertTrue(ObjectId.is_valid(data["id"]))
        self.assertEqual(data["year"], 2023)
        self.assertEqual(data["collection"], "patents_2023")
        self.assertEqual(data["application_number"], "9999/DELNP/2023")
        self.assertEqual(data["title_of_invention"], "INNOVATIVE SOLAR PANEL COATING")
        self.assertEqual(data["field_of_invention"], "ELECTRICAL")
        self.assertEqual(data["no_of_pages"], 32)
        self.assertEqual(data["no_of_claims"], 14)

        # Verify it was inserted in the test database collection patents_2023
        stored_doc = self.test_db["patents_2023"].find_one({"_id": ObjectId(data["id"])})
        self.assertIsNotNone(stored_doc)
        self.assertEqual(stored_doc["APPLICATION_NUMBER"], "9999/DELNP/2023")

    def test_09_create_duplicate_application_number_rejected_409(self):
        """Attempting to create a duplicate APPLICATION_NUMBER must return 409 Conflict."""
        payload = {
            "application_number": "DUP/APP/2021",
            "title_of_invention": "First Invention",
            "publication_date": "01/05/2021"
        }
        # First creation succeeds
        res1 = self.client.post("/api/admin/patents", headers=self.admin_headers, json=payload)
        self.assertEqual(res1.status_code, 201)

        # Second creation with identical APPLICATION_NUMBER must fail with 409
        payload2 = {
            "application_number": "DUP/APP/2021",
            "title_of_invention": "Second Invention With Same App Number",
            "publication_date": "10/10/2021"
        }
        res2 = self.client.post("/api/admin/patents", headers=self.admin_headers, json=payload2)
        self.assertEqual(res2.status_code, 409)
        self.assertIn("already exists", res2.json()["detail"])

    # -------------------------------------------------------------------------
    # 4. Retrieve & 404 Tests
    # -------------------------------------------------------------------------
    def test_10_retrieve_patent_by_id(self):
        """Admin can retrieve individual patent details by ID."""
        payload = {
            "application_number": "GET/APP/2020",
            "title_of_invention": "DRUG DELIVERY SYSTEM",
            "publication_date": "20/04/2020",
            "field_of_invention": "PHARMACEUTICAL"
        }
        create_res = self.client.post("/api/admin/patents", headers=self.admin_headers, json=payload)
        patent_id = create_res.json()["id"]

        get_res = self.client.get(f"/api/admin/patents/{patent_id}", headers=self.admin_headers)
        self.assertEqual(get_res.status_code, 200)
        data = get_res.json()
        self.assertEqual(data["id"], patent_id)
        self.assertEqual(data["application_number"], "GET/APP/2020")
        self.assertEqual(data["year"], 2020)

    def test_11_retrieve_nonexistent_patent_returns_404(self):
        """Retrieving a non-existent patent returns 404 Not Found."""
        dummy_id = str(ObjectId())
        res = self.client.get(f"/api/admin/patents/{dummy_id}", headers=self.admin_headers)
        self.assertEqual(res.status_code, 404)
        self.assertIn("not found", res.json()["detail"])

    # -------------------------------------------------------------------------
    # 5. List, Filter & Pagination Tests
    # -------------------------------------------------------------------------
    def test_12_list_patents_pagination_and_filters(self):
        """List endpoint supports pagination, text query, and attribute filters."""
        # Seed 3 patents across 2022 and 2023
        p1 = {
            "application_number": "APP/LIST/1",
            "title_of_invention": "SOLAR ENERGY GENERATOR",
            "publication_date": "01/01/2023",
            "ipo_location": "Delhi",
            "field_of_invention": "ENERGY"
        }
        p2 = {
            "application_number": "APP/LIST/2",
            "title_of_invention": "WIND ENERGY TURBINE",
            "publication_date": "01/02/2023",
            "ipo_location": "Mumbai",
            "field_of_invention": "ENERGY"
        }
        p3 = {
            "application_number": "APP/LIST/3",
            "title_of_invention": "PHARMACEUTICAL COMPOSITION",
            "publication_date": "01/01/2022",
            "ipo_location": "Delhi",
            "field_of_invention": "CHEMISTRY"
        }
        self.client.post("/api/admin/patents", headers=self.admin_headers, json=p1)
        self.client.post("/api/admin/patents", headers=self.admin_headers, json=p2)
        self.client.post("/api/admin/patents", headers=self.admin_headers, json=p3)

        # 1. List all (page 1, page_size 2)
        res = self.client.get("/api/admin/patents?page=1&page_size=2", headers=self.admin_headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["total"], 3)
        self.assertEqual(len(data["items"]), 2)
        self.assertEqual(data["total_pages"], 2)

        # 2. Filter by search query 'ENERGY'
        res_q = self.client.get("/api/admin/patents?q=ENERGY", headers=self.admin_headers)
        self.assertEqual(res_q.status_code, 200)
        self.assertEqual(res_q.json()["total"], 2)

        # 3. Filter by IPO location 'Mumbai'
        res_loc = self.client.get("/api/admin/patents?ipo_location=Mumbai", headers=self.admin_headers)
        self.assertEqual(res_loc.status_code, 200)
        self.assertEqual(res_loc.json()["total"], 1)
        self.assertEqual(res_loc.json()["items"][0]["application_number"], "APP/LIST/2")

        # 4. Filter by year 2022
        res_yr = self.client.get("/api/admin/patents?year=2022", headers=self.admin_headers)
        self.assertEqual(res_yr.status_code, 200)
        self.assertEqual(res_yr.json()["total"], 1)
        self.assertEqual(res_yr.json()["items"][0]["application_number"], "APP/LIST/3")

    # -------------------------------------------------------------------------
    # 6. Update Tests
    # -------------------------------------------------------------------------
    def test_13_update_patent_in_place(self):
        """Updating title and claims updates the document and preserves ObjectId."""
        payload = {
            "application_number": "UPDATE/01",
            "title_of_invention": "Original Title",
            "publication_date": "05/05/2023",
            "no_of_claims": 5
        }
        create_res = self.client.post("/api/admin/patents", headers=self.admin_headers, json=payload)
        patent_id = create_res.json()["id"]

        update_payload = {
            "title_of_invention": "Revised Improved Title",
            "no_of_claims": 10
        }
        put_res = self.client.put(f"/api/admin/patents/{patent_id}", headers=self.admin_headers, json=update_payload)
        self.assertEqual(put_res.status_code, 200)
        updated_data = put_res.json()

        self.assertEqual(updated_data["id"], patent_id)
        self.assertEqual(updated_data["title_of_invention"], "Revised Improved Title")
        self.assertEqual(updated_data["no_of_claims"], 10)
        self.assertEqual(updated_data["application_number"], "UPDATE/01")

    def test_14_update_patent_application_number_duplicate_collision(self):
        """Updating an application number to collide with an existing one returns 409."""
        p1 = {"application_number": "EXISTING/01", "title_of_invention": "P1", "publication_date": "01/01/2023"}
        p2 = {"application_number": "EXISTING/02", "title_of_invention": "P2", "publication_date": "01/01/2023"}

        self.client.post("/api/admin/patents", headers=self.admin_headers, json=p1)
        res2 = self.client.post("/api/admin/patents", headers=self.admin_headers, json=p2)
        id2 = res2.json()["id"]

        # Attempt to change p2's application number to EXISTING/01
        put_res = self.client.put(
            f"/api/admin/patents/{id2}",
            headers=self.admin_headers,
            json={"application_number": "EXISTING/01"}
        )
        self.assertEqual(put_res.status_code, 409)
        self.assertIn("already exists", put_res.json()["detail"])

    def test_15_update_patent_year_migration(self):
        """Updating publication_date to another year moves document to target collection preserving _id."""
        payload = {
            "application_number": "MIGRATE/01",
            "title_of_invention": "Migration Test",
            "publication_date": "01/01/2023"  # In 2023
        }
        res = self.client.post("/api/admin/patents", headers=self.admin_headers, json=payload)
        patent_id = res.json()["id"]
        doc_oid = ObjectId(patent_id)

        # Verify in patents_2023
        self.assertIsNotNone(self.test_db["patents_2023"].find_one({"_id": doc_oid}))

        # Update publication date to 2018
        put_res = self.client.put(
            f"/api/admin/patents/{patent_id}",
            headers=self.admin_headers,
            json={"publication_date": "05/05/2018"}
        )
        self.assertEqual(put_res.status_code, 200)
        self.assertEqual(put_res.json()["year"], 2018)
        self.assertEqual(put_res.json()["collection"], "patents_2018")

        # Verify moved from patents_2023 to patents_2018 with identical _id
        self.assertIsNone(self.test_db["patents_2023"].find_one({"_id": doc_oid}))
        self.assertIsNotNone(self.test_db["patents_2018"].find_one({"_id": doc_oid}))

    # -------------------------------------------------------------------------
    # 7. Delete Tests
    # -------------------------------------------------------------------------
    def test_16_delete_patent_success(self):
        """Admin can delete a patent; subsequent retrieval returns 404."""
        payload = {
            "application_number": "DELETE/01",
            "title_of_invention": "To Be Deleted",
            "publication_date": "10/10/2022"
        }
        create_res = self.client.post("/api/admin/patents", headers=self.admin_headers, json=payload)
        patent_id = create_res.json()["id"]

        del_res = self.client.delete(f"/api/admin/patents/{patent_id}", headers=self.admin_headers)
        self.assertEqual(del_res.status_code, 200)
        self.assertTrue(del_res.json()["success"])
        self.assertEqual(del_res.json()["id"], patent_id)

        # Retrieval should now 404
        get_res = self.client.get(f"/api/admin/patents/{patent_id}", headers=self.admin_headers)
        self.assertEqual(get_res.status_code, 404)

    def test_17_delete_nonexistent_patent_returns_404(self):
        """Deleting a non-existent patent returns 404."""
        dummy_id = str(ObjectId())
        res = self.client.delete(f"/api/admin/patents/{dummy_id}", headers=self.admin_headers)
        self.assertEqual(res.status_code, 404)


if __name__ == "__main__":
    unittest.main()
