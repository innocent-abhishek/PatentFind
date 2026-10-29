import unittest
from unittest.mock import patch
from bson import ObjectId
from pymongo import MongoClient

from app.core.config import settings
from app.indexing.index_sync import (
    sync_index_patent_created,
    sync_index_patent_updated,
    sync_index_patent_deleted,
    reconcile_patent_index,
    _add_term_posting
)
from app.search.searcher import search_patents
from app.services.admin_patent_service import (
    create_patent,
    update_patent,
    delete_patent
)
from app.schemas.admin_patents import PatentCreateRequest, PatentUpdateRequest

TEST_DB_NAME = "patentfind_test_index_sync_phase3"


class TestIndexSyncPhase3(unittest.TestCase):
    """
    Automated test suite for Phase 3: Persistent Inverted-Index Synchronization.
    Verifies all 11 requirements in complete isolation using a dedicated test database.
    Never alters existing production records.
    """

    @classmethod
    def setUpClass(cls):
        cls.mongo_client = MongoClient(settings.MONGODB_URL, serverSelectionTimeoutMS=5000)
        cls.test_db = cls.mongo_client[TEST_DB_NAME]

        # Patch db across relevant modules
        cls.patchers = [
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
    # Requirement 1 & 2: Creating a patent adds terms & appears in search immediately
    # -------------------------------------------------------------------------
    def test_01_create_patent_adds_terms_and_appears_in_search(self):
        """Creating a patent must immediately index its terms and make it findable via search_patents."""
        req = PatentCreateRequest(
            application_number="SYNC/01",
            title_of_invention="QUANTUM CRYPTOGRAPHY TRANSCEIVER",
            field_of_invention="TELECOMMUNICATIONS",
            publication_date="15/06/2023",
            publication_number="24/2023",
            ipo_location="Delhi"
        )
        created = create_patent(req, target_db=self.test_db)
        doc_oid = ObjectId(created.id)

        # 1. Verify terms exist in inverted_index
        quantum_chunk = self.test_db[settings.INVERTED_INDEX_COLLECTION].find_one({"term": "quantum"})
        self.assertIsNotNone(quantum_chunk)
        self.assertEqual(quantum_chunk["doc_count"], 1)
        self.assertEqual(quantum_chunk["postings"][0]["id"], doc_oid)
        self.assertEqual(quantum_chunk["postings"][0]["y"], 2023)

        crypto_chunk = self.test_db[settings.INVERTED_INDEX_COLLECTION].find_one({"term": "cryptography"})
        self.assertIsNotNone(crypto_chunk)

        # 2. Verify search_patents returns the new patent immediately
        res = search_patents("quantum cryptography", page=1, page_size=10)
        self.assertEqual(res.total, 1)
        self.assertEqual(res.results[0].id, created.id)
        self.assertEqual(res.results[0].title, "QUANTUM CRYPTOGRAPHY TRANSCEIVER")

    # -------------------------------------------------------------------------
    # Requirement 3: Updating title removes old terms & adds new terms
    # -------------------------------------------------------------------------
    def test_02_update_title_removes_old_terms_and_adds_new_terms(self):
        """Updating title removes old terms and adds new terms without rebuilding index."""
        req = PatentCreateRequest(
            application_number="SYNC/02",
            title_of_invention="HYDROGEN FUEL CATALYST",
            field_of_invention="CHEMISTRY",
            publication_date="01/01/2023"
        )
        created = create_patent(req, target_db=self.test_db)

        # Search for 'hydrogen' finds 1 result
        res1 = search_patents("hydrogen", page=1, page_size=10)
        self.assertEqual(res1.total, 1)

        # Update title: replace 'hydrogen fuel' with 'graphene solar'
        update_req = PatentUpdateRequest(
            title_of_invention="GRAPHENE SOLAR CATALYST"
        )
        update_patent(created.id, update_req, target_db=self.test_db)

        # 'hydrogen' must now return 0 results
        res_old = search_patents("hydrogen", page=1, page_size=10)
        self.assertEqual(res_old.total, 0)

        # 'graphene' must now return 1 result
        res_new = search_patents("graphene", page=1, page_size=10)
        self.assertEqual(res_new.total, 1)
        self.assertEqual(res_new.results[0].id, created.id)

        # Unchanged term 'catalyst' and 'chemistry' still match
        res_unchanged = search_patents("catalyst chemistry", page=1, page_size=10)
        self.assertEqual(res_unchanged.total, 1)

    # -------------------------------------------------------------------------
    # Requirement 4: Updating field of invention synchronizes terms
    # -------------------------------------------------------------------------
    def test_03_update_field_of_invention_synchronizes_terms(self):
        """Updating field of invention adds and removes corresponding terms in inverted index."""
        req = PatentCreateRequest(
            application_number="SYNC/03",
            title_of_invention="MICROELECTRONIC SENSOR",
            field_of_invention="BIOTECHNOLOGY",
            publication_date="10/10/2022"
        )
        created = create_patent(req, target_db=self.test_db)

        res_bio = search_patents("biotechnology", page=1, page_size=10)
        self.assertEqual(res_bio.total, 1)

        # Change field to NANOTECHNOLOGY
        update_req = PatentUpdateRequest(field_of_invention="NANOTECHNOLOGY")
        update_patent(created.id, update_req, target_db=self.test_db)

        # Biotechnology must return 0
        self.assertEqual(search_patents("biotechnology", page=1, page_size=10).total, 0)
        # Nanotechnology must return 1
        res_nano = search_patents("nanotechnology", page=1, page_size=10)
        self.assertEqual(res_nano.total, 1)
        self.assertEqual(res_nano.results[0].id, created.id)

    # -------------------------------------------------------------------------
    # Requirement 5: Updating unrelated metadata does not duplicate postings
    # -------------------------------------------------------------------------
    def test_04_update_unrelated_metadata_no_duplicate_postings(self):
        """Updating claims, pages, or location does not modify postings or cause duplicates."""
        req = PatentCreateRequest(
            application_number="SYNC/04",
            title_of_invention="AUTONOMOUS DRONE NAVIGATION",
            field_of_invention="ROBOTICS",
            publication_date="20/05/2023",
            no_of_claims=5,
            no_of_pages=12
        )
        created = create_patent(req, target_db=self.test_db)

        # Update unrelated metadata (no_of_claims, no_of_pages, ipo_location)
        update_req = PatentUpdateRequest(no_of_claims=25, no_of_pages=50, ipo_location="Chennai")
        update_patent(created.id, update_req, target_db=self.test_db)

        # Verify drone posting count is still exactly 1
        chunk = self.test_db[settings.INVERTED_INDEX_COLLECTION].find_one({"term": "drone"})
        self.assertEqual(chunk["doc_count"], 1)
        self.assertEqual(len(chunk["postings"]), 1)

        # Search still returns exactly 1 result
        res = search_patents("drone", page=1, page_size=10)
        self.assertEqual(res.total, 1)

    # -------------------------------------------------------------------------
    # Requirement 6: Deleting a patent removes its postings and search results
    # -------------------------------------------------------------------------
    def test_05_delete_patent_removes_postings_and_search_results(self):
        """Deleting a patent completely eliminates its postings and makes it unsearchable."""
        req = PatentCreateRequest(
            application_number="SYNC/05",
            title_of_invention="SUPERCONDUCTING MAGNET APPARATUS",
            field_of_invention="PHYSICS",
            publication_date="01/01/2021"
        )
        created = create_patent(req, target_db=self.test_db)

        # Verify indexed
        self.assertEqual(search_patents("superconducting", page=1, page_size=10).total, 1)

        # Delete patent
        delete_patent(created.id, target_db=self.test_db)

        # Search returns 0
        self.assertEqual(search_patents("superconducting", page=1, page_size=10).total, 0)

        # Check inverted_index collection: empty chunk should have been removed
        magnet_chunk = self.test_db[settings.INVERTED_INDEX_COLLECTION].find_one({"term": "superconducting"})
        self.assertIsNone(magnet_chunk)

    # -------------------------------------------------------------------------
    # Requirement 7: Updating publication year migrates postings correctly
    # -------------------------------------------------------------------------
    def test_06_update_publication_year_migrates_postings(self):
        """When publication year changes from 2023 to 2019, index posting year is updated to 2019."""
        req = PatentCreateRequest(
            application_number="SYNC/06",
            title_of_invention="WIND GENERATOR BLADE",
            field_of_invention="ENERGY",
            publication_date="01/01/2023"
        )
        created = create_patent(req, target_db=self.test_db)
        doc_oid = ObjectId(created.id)

        # Check initial posting has year 2023
        chunk_init = self.test_db[settings.INVERTED_INDEX_COLLECTION].find_one({"term": "blade"})
        self.assertEqual(chunk_init["postings"][0]["y"], 2023)

        # Update publication date to 2019
        update_req = PatentUpdateRequest(publication_date="15/07/2019")
        update_patent(created.id, update_req, target_db=self.test_db)

        # Check updated posting in inverted index now has year 2019
        chunk_migrated = self.test_db[settings.INVERTED_INDEX_COLLECTION].find_one({"term": "blade"})
        self.assertEqual(chunk_migrated["postings"][0]["y"], 2019)
        self.assertEqual(chunk_migrated["postings"][0]["id"], doc_oid)

        # Search returns the record and reflects year 2019 and collection patents_2019
        res = search_patents("blade", page=1, page_size=10)
        self.assertEqual(res.total, 1)
        self.assertEqual(res.results[0].year, 2019)
        self.assertEqual(res.results[0].collection, "patents_2019")

    # -------------------------------------------------------------------------
    # Requirement 8: Repeated synchronization does not duplicate postings
    # -------------------------------------------------------------------------
    def test_07_repeated_synchronization_does_not_duplicate_postings(self):
        """Calling sync_index_patent_created multiple times on the same document is idempotent."""
        doc = {
            "_id": ObjectId(),
            "TITLE_OF_INVENTION": "SOLAR CELL ARRAY",
            "FIELD_OF_INVENTION": "ENERGY"
        }
        # First sync
        sync_index_patent_created(doc, 2023, target_db=self.test_db)
        chunk1 = self.test_db[settings.INVERTED_INDEX_COLLECTION].find_one({"term": "solar"})
        self.assertEqual(chunk1["doc_count"], 1)
        self.assertEqual(len(chunk1["postings"]), 1)

        # Second sync on same document
        sync_index_patent_created(doc, 2023, target_db=self.test_db)
        chunk2 = self.test_db[settings.INVERTED_INDEX_COLLECTION].find_one({"term": "solar"})
        self.assertEqual(chunk2["doc_count"], 1)
        self.assertEqual(len(chunk2["postings"]), 1)

    # -------------------------------------------------------------------------
    # Requirement 9: Chunk boundaries and doc_count remain correct
    # -------------------------------------------------------------------------
    def test_08_chunk_boundaries_and_doc_count_consistency(self):
        """Postings beyond chunk size create chunk_id=1, keeping doc_count consistent."""
        term = "testchunkterm"
        idx_col = self.test_db[settings.INVERTED_INDEX_COLLECTION]

        # Simulate small chunk threshold to verify chunking logic
        with patch.object(settings, "POSTINGS_CHUNK_SIZE", 3):
            id1 = ObjectId()
            id2 = ObjectId()
            id3 = ObjectId()
            id4 = ObjectId()

            _add_term_posting(idx_col, term, 2023, id1)
            _add_term_posting(idx_col, term, 2023, id2)
            _add_term_posting(idx_col, term, 2023, id3)

            # Chunk 0 should have 3 postings
            c0 = idx_col.find_one({"term": term, "chunk_id": 0})
            self.assertIsNotNone(c0)
            self.assertEqual(c0["doc_count"], 3)
            self.assertEqual(len(c0["postings"]), 3)

            # 4th item should trigger chunk_id=1
            _add_term_posting(idx_col, term, 2023, id4)
            c1 = idx_col.find_one({"term": term, "chunk_id": 1})
            self.assertIsNotNone(c1)
            self.assertEqual(c1["doc_count"], 1)
            self.assertEqual(len(c1["postings"]), 1)

    # -------------------------------------------------------------------------
    # Requirement 10: Failures are detected & recoverable with compensating rollback
    # -------------------------------------------------------------------------
    def test_09_failure_in_index_sync_rolls_back_mongodb_cleanly(self):
        """If index sync fails during creation, MongoDB insertion is rolled back cleanly."""
        req = PatentCreateRequest(
            application_number="FAIL/01",
            title_of_invention="FAIL TEST PATENT",
            publication_date="01/01/2023"
        )

        with patch("app.services.admin_patent_service.sync_index_patent_created", side_effect=RuntimeError("Simulated index disk full")):
            with self.assertRaises(Exception) as ctx:
                create_patent(req, target_db=self.test_db)

            # Verify rolled back: no document in patents_2023
            doc = self.test_db["patents_2023"].find_one({"APPLICATION_NUMBER": "FAIL/01"})
            self.assertIsNone(doc)

    # -------------------------------------------------------------------------
    # Requirement 10 (cont.): Reconciliation mechanism
    # -------------------------------------------------------------------------
    def test_10_reconciliation_fixes_stale_and_missing_postings(self):
        """reconcile_patent_index repairs inconsistencies between document and index."""
        patent_id = ObjectId()
        doc = {
            "_id": patent_id,
            "APPLICATION_NUMBER": "RECON/01",
            "TITLE_OF_INVENTION": "AI PROCESSOR ACCELERATOR",
            "FIELD_OF_INVENTION": "COMPUTING"
        }
        self.test_db["patents_2023"].insert_one(doc)

        # Intentionally inject stale posting 'obsolete' and omit 'processor'
        idx_col = self.test_db[settings.INVERTED_INDEX_COLLECTION]
        _add_term_posting(idx_col, "obsolete", 2023, patent_id)
        _add_term_posting(idx_col, "ai", 2023, patent_id)

        # Run reconciliation
        recon_res = reconcile_patent_index(doc, 2023, target_db=self.test_db)
        self.assertTrue(recon_res["success"])
        self.assertEqual(recon_res["stale_terms_removed"], 1)  # 'obsolete' removed
        self.assertGreater(recon_res["missing_terms_added"], 0)  # 'processor', 'accelerator', 'computing' added

        # Obsolete posting must be gone
        self.assertIsNone(idx_col.find_one({"term": "obsolete", "postings.id": patent_id}))
        # Expected terms must be present
        self.assertIsNotNone(idx_col.find_one({"term": "processor", "postings.id": patent_id}))


if __name__ == "__main__":
    unittest.main()
