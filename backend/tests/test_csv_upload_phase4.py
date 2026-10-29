import io
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from pymongo import MongoClient

from app.main import app
from app.core.config import settings
from app.core.security import create_access_token

TEST_DB_NAME = "patentfind_test_csv_phase4"


class TestCsvUploadPhase4(unittest.TestCase):
    """
    Automated test suite for Phase 4: Admin CSV Patent Upload.
    Tests file parsing, validation, deduplication, batch index sync, and RBAC
    in complete isolation using a dedicated test database.
    """

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.mongo_client = MongoClient(settings.MONGODB_URL, serverSelectionTimeoutMS=5000)
        cls.test_db = cls.mongo_client[TEST_DB_NAME]

        # Auth tokens
        cls.admin_token = create_access_token(
            data={"sub": "admin_csv", "username": "admin_csv_user", "role": "admin"}
        )
        cls.admin_headers = {"Authorization": f"Bearer {cls.admin_token}"}

        cls.user_token = create_access_token(
            data={"sub": "reg_csv", "username": "regular_user", "role": "user"}
        )
        cls.user_headers = {"Authorization": f"Bearer {cls.user_token}"}

        # Patch db across relevant modules
        cls.patchers = [
            patch("app.services.csv_import_service.db", cls.test_db),
            patch("app.indexing.index_sync.db", cls.test_db),
            patch("app.services.admin_patent_service.db", cls.test_db),
            patch("app.search.searcher.db", cls.test_db),
            patch("app.indexing.indexer.db", cls.test_db),
        ]
        for p in cls.patchers:
            p.start()

    @classmethod
    def tearDownClass(cls):
        for p in cls.patchers:
            p.stop()
        cls.mongo_client.drop_database(TEST_DB_NAME)
        cls.mongo_client.close()

    def setUp(self):
        # Reset collections in the isolated test database before each test
        for year in settings.PATENT_YEARS:
            self.test_db[f"patents_{year}"].delete_many({})
        self.test_db[settings.INVERTED_INDEX_COLLECTION].delete_many({})
        self.test_db[settings.METADATA_COLLECTION].delete_many({})
        self.test_db["index_sync_log"].delete_many({})

        # Initialize index metadata as ready
        self.test_db[settings.METADATA_COLLECTION].insert_one({
            "_id": "index_status",
            "status": "ready",
            "is_indexed": True,
            "total_records": 0,
            "unique_terms": 0,
            "total_postings": 0,
            "collections_indexed": settings.PATENT_COLLECTIONS
        })

    # -------------------------------------------------------------------------
    # 1. RBAC & Authentication Checks (401 & 403)
    # -------------------------------------------------------------------------
    def test_01_upload_csv_unauthenticated_returns_401(self):
        """Unauthenticated requests to upload-csv must receive 401."""
        csv_content = b"APPLICATION_NUMBER,TITLE_OF_INVENTION,PUBLICATION_DATE\n1,Test,01/01/2023"
        files = {"file": ("patents.csv", csv_content, "text/csv")}
        res = self.client.post("/api/admin/patents/upload-csv", files=files)
        self.assertEqual(res.status_code, 401)
        self.assertIn("Not authenticated", res.json()["detail"])

    def test_02_upload_csv_regular_user_returns_403(self):
        """Regular users (role='user') must receive 403 Forbidden."""
        csv_content = b"APPLICATION_NUMBER,TITLE_OF_INVENTION,PUBLICATION_DATE\n1,Test,01/01/2023"
        files = {"file": ("patents.csv", csv_content, "text/csv")}
        res = self.client.post("/api/admin/patents/upload-csv", headers=self.user_headers, files=files)
        self.assertEqual(res.status_code, 403)
        self.assertIn("Administrator privileges required", res.json()["detail"])

    # -------------------------------------------------------------------------
    # 2. File Format, Headers & Empty File Checks
    # -------------------------------------------------------------------------
    def test_03_upload_non_csv_file_rejected(self):
        """Uploading a non-CSV file (e.g. .txt or .json) returns 400 Bad Request."""
        files = {"file": ("patents.txt", b"some,text,data", "text/plain")}
        res = self.client.post("/api/admin/patents/upload-csv", headers=self.admin_headers, files=files)
        self.assertEqual(res.status_code, 400)
        self.assertIn("Invalid file format", res.json()["detail"])

    def test_04_upload_empty_csv_rejected(self):
        """Uploading an empty CSV file returns 400 Bad Request."""
        files = {"file": ("empty.csv", b"", "text/csv")}
        res = self.client.post("/api/admin/patents/upload-csv", headers=self.admin_headers, files=files)
        self.assertEqual(res.status_code, 400)
        self.assertIn("empty", res.json()["detail"])

    def test_05_upload_missing_required_headers_rejected(self):
        """Uploading CSV missing required headers returns 400 Bad Request with missing columns."""
        # Missing TITLE_OF_INVENTION
        csv_data = "APPLICATION_NUMBER,PUBLICATION_DATE,IPO_LOCATION\n100/DEL/2023,01/01/2023,Delhi\n"
        files = {"file": ("patents.csv", csv_data.encode("utf-8"), "text/csv")}
        res = self.client.post("/api/admin/patents/upload-csv", headers=self.admin_headers, files=files)
        self.assertEqual(res.status_code, 400)
        self.assertIn("Missing required CSV column headers", res.json()["detail"])
        self.assertIn("TITLE_OF_INVENTION", res.json()["detail"])

    # -------------------------------------------------------------------------
    # 3. Successful Batch Import & Immediate Searchability
    # -------------------------------------------------------------------------
    def test_06_successful_csv_import_and_searchability(self):
        """Valid CSV rows are imported into appropriate annual collections and searchable immediately."""
        csv_content = (
            "APPLICATION_NUMBER,TITLE_OF_INVENTION,PUBLICATION_DATE,FIELD_OF_INVENTION,IPO_LOCATION,NO_OF_PAGES,NO_OF_CLAIMS\n"
            "CSV/APP/001,HYPERSONIC SCRAMJET PROPULSION,10/05/2023,AEROSPACE,Delhi,45,18\n"
            "CSV/APP/002,BIOCOMPATIBLE CARDIAC STENT,15/08/2022,BIOMEDICAL,Mumbai,28,10\n"
            "CSV/APP/003,SOLID STATE LITHIUM BATTERY,20/12/2021,ENERGY,Chennai,34,14\n"
        )
        files = {"file": ("patents.csv", csv_content.encode("utf-8"), "text/csv")}
        res = self.client.post("/api/admin/patents/upload-csv", headers=self.admin_headers, files=files)
        self.assertEqual(res.status_code, 200)
        summary = res.json()

        self.assertTrue(summary["success"])
        self.assertEqual(summary["total_rows"], 3)
        self.assertEqual(summary["imported_count"], 3)
        self.assertEqual(summary["duplicate_count"], 0)
        self.assertEqual(summary["failed_count"], 0)

        # Verify records stored in correct annual collections
        doc1 = self.test_db["patents_2023"].find_one({"APPLICATION_NUMBER": "CSV/APP/001"})
        self.assertIsNotNone(doc1)
        self.assertEqual(doc1["TITLE_OF_INVENTION"], "HYPERSONIC SCRAMJET PROPULSION")

        doc2 = self.test_db["patents_2022"].find_one({"APPLICATION_NUMBER": "CSV/APP/002"})
        self.assertIsNotNone(doc2)

        doc3 = self.test_db["patents_2021"].find_one({"APPLICATION_NUMBER": "CSV/APP/003"})
        self.assertIsNotNone(doc3)

        # Verify immediate searchability via /api/search
        search_res1 = self.client.get("/api/search?q=scramjet")
        self.assertEqual(search_res1.status_code, 200)
        self.assertEqual(search_res1.json()["total"], 1)
        self.assertEqual(search_res1.json()["results"][0]["application_number"], "CSV/APP/001")

        search_res2 = self.client.get("/api/search?q=cardiac+stent")
        self.assertEqual(search_res2.status_code, 200)
        self.assertEqual(search_res2.json()["total"], 1)
        self.assertEqual(search_res2.json()["results"][0]["application_number"], "CSV/APP/002")

    # -------------------------------------------------------------------------
    # 4. Duplicate Detection (In-File and Existing Database Records)
    # -------------------------------------------------------------------------
    def test_07_in_file_duplicate_application_number_skipped(self):
        """Duplicate APPLICATION_NUMBER within the same CSV file is skipped with row number."""
        csv_content = (
            "APPLICATION_NUMBER,TITLE_OF_INVENTION,PUBLICATION_DATE\n"
            "DUP/FILE/01,FIRST INVENTIVE DEVICE,01/01/2023\n"
            "DUP/FILE/01,SECOND COLLIDING RECORD,01/02/2023\n"
            "DUP/FILE/02,UNIQUE THIRD INVENTIVE DEVICE,01/03/2023\n"
        )
        files = {"file": ("duplicates.csv", csv_content.encode("utf-8"), "text/csv")}
        res = self.client.post("/api/admin/patents/upload-csv", headers=self.admin_headers, files=files)
        self.assertEqual(res.status_code, 200)
        summary = res.json()

        self.assertEqual(summary["total_rows"], 3)
        self.assertEqual(summary["imported_count"], 2)
        self.assertEqual(summary["duplicate_count"], 1)

        # Check skipped duplicate item
        dup_item = summary["skipped_duplicates"][0]
        self.assertEqual(dup_item["row"], 3)  # Row 3 in file (header is 1, first is 2, duplicate is 3)
        self.assertEqual(dup_item["application_number"], "DUP/FILE/01")
        self.assertIn("multiple times within this CSV", dup_item["reason"])

    def test_08_database_existing_duplicate_application_number_skipped(self):
        """Records matching existing MongoDB APPLICATION_NUMBER are skipped and not overwritten."""
        # Seed an existing patent in database
        self.test_db["patents_2023"].insert_one({
            "APPLICATION_NUMBER": "EXISTING/DB/01",
            "TITLE_OF_INVENTION": "ALREADY REGISTERED PATENT",
            "PUBLICATION_DATE": "01/01/2023"
        })

        csv_content = (
            "APPLICATION_NUMBER,TITLE_OF_INVENTION,PUBLICATION_DATE\n"
            "EXISTING/DB/01,OVERWRITE ATTEMPT TITLE,05/05/2023\n"
            "NEW/DB/02,BRAND NEW PATENT TITLE,05/05/2023\n"
        )
        files = {"file": ("patents.csv", csv_content.encode("utf-8"), "text/csv")}
        res = self.client.post("/api/admin/patents/upload-csv", headers=self.admin_headers, files=files)
        self.assertEqual(res.status_code, 200)
        summary = res.json()

        self.assertEqual(summary["imported_count"], 1)
        self.assertEqual(summary["duplicate_count"], 1)

        dup_item = summary["skipped_duplicates"][0]
        self.assertEqual(dup_item["row"], 2)
        self.assertEqual(dup_item["application_number"], "EXISTING/DB/01")
        self.assertIn("already exists in database", dup_item["reason"])

        # Confirm original document was NOT overwritten
        original_doc = self.test_db["patents_2023"].find_one({"APPLICATION_NUMBER": "EXISTING/DB/01"})
        self.assertEqual(original_doc["TITLE_OF_INVENTION"], "ALREADY REGISTERED PATENT")

    # -------------------------------------------------------------------------
    # 5. Row-Level Validation Errors (Dates, Numeric, Missing Values)
    # -------------------------------------------------------------------------
    def test_09_row_validation_errors_reported_with_row_numbers(self):
        """Malformed rows report exact row numbers and error descriptions without stopping other valid rows."""
        csv_content = (
            "APPLICATION_NUMBER,TITLE_OF_INVENTION,PUBLICATION_DATE,NO_OF_PAGES,NO_OF_CLAIMS\n"
            ",VALID TITLE WITH MISSING APP NUMBER,01/01/2023,10,5\n"  # Row 2: missing app num
            "VALID/APP/002,,01/01/2023,10,5\n"                         # Row 3: missing title
            "VALID/APP/003,INVALID DATE FORMAT,2023-01-01,10,5\n"      # Row 4: YYYY-MM-DD instead of DD/MM/YYYY
            "VALID/APP/004,UNSUPPORTED YEAR,01/01/2025,10,5\n"         # Row 5: year 2025 outside 2016-2023
            "VALID/APP/005,INVALID NUMERIC,01/01/2023,not-a-num,-4\n"  # Row 6: invalid pages & claims
            "VALID/APP/006,COMPLETELY VALID RECORD,01/01/2023,15,8\n"  # Row 7: valid
        )
        files = {"file": ("errors.csv", csv_content.encode("utf-8"), "text/csv")}
        res = self.client.post("/api/admin/patents/upload-csv", headers=self.admin_headers, files=files)
        self.assertEqual(res.status_code, 200)
        summary = res.json()

        self.assertEqual(summary["total_rows"], 6)
        self.assertEqual(summary["imported_count"], 1)  # Only row 7
        self.assertGreaterEqual(summary["failed_count"], 5)

        err_rows = [e["row"] for e in summary["validation_errors"]]
        self.assertIn(2, err_rows)
        self.assertIn(3, err_rows)
        self.assertIn(4, err_rows)
        self.assertIn(5, err_rows)
        self.assertIn(6, err_rows)

    # -------------------------------------------------------------------------
    # 6. File Limits (Max Size & Max Rows)
    # -------------------------------------------------------------------------
    def test_10_oversized_file_rejected_with_413(self):
        """Files exceeding MAX_CSV_UPLOAD_BYTES are rejected with 413 Payload Too Large."""
        with patch.object(settings, "MAX_CSV_UPLOAD_BYTES", 500):  # 500 bytes limit
            large_content = b"APPLICATION_NUMBER,TITLE_OF_INVENTION,PUBLICATION_DATE\n" + (b"A,B,01/01/2023\n" * 50)
            files = {"file": ("toolarge.csv", large_content, "text/csv")}
            res = self.client.post("/api/admin/patents/upload-csv", headers=self.admin_headers, files=files)
            self.assertEqual(res.status_code, 413)
            self.assertIn("exceeds the maximum allowed limit", res.json()["detail"])

    def test_11_max_rows_limit_rejected_with_400(self):
        """CSV files exceeding MAX_CSV_ROWS are rejected with 400 Bad Request."""
        with patch.object(settings, "MAX_CSV_ROWS", 2):  # Limit 2 rows
            csv_content = (
                "APPLICATION_NUMBER,TITLE_OF_INVENTION,PUBLICATION_DATE\n"
                "1,A,01/01/2023\n"
                "2,B,01/01/2023\n"
                "3,C,01/01/2023\n"
            )
            files = {"file": ("manyrows.csv", csv_content.encode("utf-8"), "text/csv")}
            res = self.client.post("/api/admin/patents/upload-csv", headers=self.admin_headers, files=files)
            self.assertEqual(res.status_code, 400)
            self.assertIn("exceeds the maximum allowed limit of 2 data rows", res.json()["detail"])


if __name__ == "__main__":
    unittest.main()
