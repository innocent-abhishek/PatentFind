import math
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
from bson import ObjectId
from fastapi import HTTPException, status
from pymongo.database import Database

from app.core.config import settings
from app.db.mongodb import db
from app.indexing.index_sync import (
    sync_index_patent_created,
    sync_index_patent_updated,
    sync_index_patent_deleted
)
from app.schemas.admin_patents import (
    PatentCreateRequest,
    PatentUpdateRequest,
    PatentResponse,
    PatentListResponse,
    PatentDeleteResponse
)


def validate_object_id(patent_id: str) -> ObjectId:
    """Validates that a string is a 24-character hexadecimal MongoDB ObjectId."""
    if not isinstance(patent_id, str) or not ObjectId.is_valid(patent_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid patent ID format. Must be a 24-character hexadecimal string."
        )
    return ObjectId(patent_id)


def resolve_year_from_date(date_str: str) -> int:
    """
    Extracts the 4-digit year from a DD/MM/YYYY date string and verifies
    that it matches a supported patent collection year (2016-2023).
    """
    if not date_str or not isinstance(date_str, str):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Publication date is required to determine the patent collection."
        )
    parts = date_str.strip().split("/")
    if len(parts) != 3 or not parts[2].isdigit():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Publication date must be in DD/MM/YYYY format."
        )
    year = int(parts[2])
    if year not in settings.PATENT_YEARS:
        min_yr = min(settings.PATENT_YEARS)
        max_yr = max(settings.PATENT_YEARS)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Publication year '{year}' is not supported. Supported patent collection years are {min_yr} through {max_yr}."
        )
    return year


def doc_to_patent_response(doc: dict, year: int) -> PatentResponse:
    """Maps a MongoDB document to a PatentResponse schema object."""
    def safe_str(v):
        return str(v) if v is not None else None

    def safe_int(v):
        if v is None:
            return None
        try:
            return int(v)
        except (ValueError, TypeError):
            return None

    return PatentResponse(
        id=str(doc.get("_id")),
        year=year,
        collection=f"patents_{year}",
        application_number=str(doc.get("APPLICATION_NUMBER", "")),
        publication_number=safe_str(doc.get("PUBLICATION_NUMBER")),
        publication_date=safe_str(doc.get("PUBLICATION_DATE")),
        date_of_filing=safe_str(doc.get("DATE_OF_FILING")),
        ipo_location=safe_str(doc.get("IPO_LOCATION")),
        application_type_desc=safe_str(doc.get("APPLICATION_TYPE_DESC")),
        title_of_invention=safe_str(doc.get("TITLE_OF_INVENTION")),
        field_of_invention=safe_str(doc.get("FIELD_OF_INVENTION")),
        no_of_pages=safe_int(doc.get("NO_OF_PAGES")),
        no_of_claims=safe_int(doc.get("NO_OF_CLAIMS")),
        date_updated_d_m_y=safe_str(doc.get("DATE_UPDATED_d_m_y"))
    )


def find_patent_by_id(patent_id: str, target_db: Optional[Database] = None) -> Tuple[dict, int, str]:
    """
    Locates a patent document across collections patents_2016 through patents_2023 using ObjectId.
    Returns (doc, year, collection_name).
    Raises HTTP 404 if not found in any collection.
    """
    database = target_db if target_db is not None else db
    doc_id = validate_object_id(patent_id)

    # Search in reverse chronological order (2023 down to 2016)
    for year in reversed(settings.PATENT_YEARS):
        col_name = f"patents_{year}"
        doc = database[col_name].find_one({"_id": doc_id})
        if doc:
            return doc, year, col_name

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Patent with ID '{patent_id}' was not found in any collection."
    )


def check_duplicate_application_number(
    application_number: str,
    exclude_id: Optional[ObjectId] = None,
    target_db: Optional[Database] = None
) -> None:
    """
    Checks if an APPLICATION_NUMBER is already registered across any patent collection.
    Raises HTTP 409 Conflict if a collision is found.
    """
    database = target_db if target_db is not None else db
    clean_app_no = application_number.strip()
    query: Dict[str, Any] = {"APPLICATION_NUMBER": clean_app_no}
    if exclude_id is not None:
        query["_id"] = {"$ne": exclude_id}

    for year in settings.PATENT_YEARS:
        col_name = f"patents_{year}"
        existing = database[col_name].find_one(query, {"_id": 1, "APPLICATION_NUMBER": 1})
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Patent with Application Number '{clean_app_no}' already exists in {col_name}."
            )


def list_patents(
    page: int = 1,
    page_size: int = 10,
    q: Optional[str] = None,
    ipo_location: Optional[str] = None,
    field_of_invention: Optional[str] = None,
    year: Optional[int] = None,
    target_db: Optional[Database] = None
) -> PatentListResponse:
    """
    Lists patent records with pagination, text filtering, and attribute filters across
    the annual patent collections.
    """
    database = target_db if target_db is not None else db

    if page < 1:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Page must be >= 1.")
    if page_size < 1 or page_size > 100:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Page size must be between 1 and 100.")

    # Determine which years/collections to query
    if year is not None:
        if year not in settings.PATENT_YEARS:
            min_yr = min(settings.PATENT_YEARS)
            max_yr = max(settings.PATENT_YEARS)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Year '{year}' is outside supported collection range ({min_yr}-{max_yr})."
            )
        years_to_query = [year]
    else:
        # Default order: newest year first (2023 -> 2016)
        years_to_query = list(reversed(settings.PATENT_YEARS))

    # Build Mongo filter query
    mongo_filter: Dict[str, Any] = {}
    if ipo_location and ipo_location.strip():
        clean_loc = ipo_location.strip()
        mongo_filter["IPO_LOCATION"] = {"$regex": f"^{re.escape(clean_loc)}$", "$options": "i"}

    if field_of_invention and field_of_invention.strip():
        clean_field = field_of_invention.strip()
        mongo_filter["FIELD_OF_INVENTION"] = {"$regex": re.escape(clean_field), "$options": "i"}

    if q and q.strip():
        clean_q = q.strip()
        escaped_q = re.escape(clean_q)
        mongo_filter["$or"] = [
            {"APPLICATION_NUMBER": {"$regex": escaped_q, "$options": "i"}},
            {"TITLE_OF_INVENTION": {"$regex": escaped_q, "$options": "i"}},
            {"FIELD_OF_INVENTION": {"$regex": escaped_q, "$options": "i"}},
            {"PUBLICATION_NUMBER": {"$regex": escaped_q, "$options": "i"}},
        ]

    # Calculate collection counts and total matches
    col_counts: List[Tuple[int, str, int]] = []
    total_matches = 0
    for yr in years_to_query:
        col_name = f"patents_{yr}"
        cnt = database[col_name].count_documents(mongo_filter)
        col_counts.append((yr, col_name, cnt))
        total_matches += cnt

    total_pages = math.ceil(total_matches / page_size) if total_matches > 0 else 0

    if total_matches == 0:
        return PatentListResponse(
            total=0,
            page=page,
            page_size=page_size,
            total_pages=0,
            items=[]
        )

    # Windowed pagination slice across collections
    skip = (page - 1) * page_size
    items_to_take = page_size
    collected_items: List[PatentResponse] = []

    for yr, col_name, cnt in col_counts:
        if cnt == 0:
            continue
        if skip >= cnt:
            skip -= cnt
            continue

        # In this collection, we take documents starting from 'skip'
        take_from_col = min(items_to_take, cnt - skip)
        cursor = (
            database[col_name]
            .find(mongo_filter)
            .sort([("_id", -1)])
            .skip(skip)
            .limit(take_from_col)
        )
        for doc in cursor:
            collected_items.append(doc_to_patent_response(doc, yr))

        items_to_take -= take_from_col
        skip = 0  # for subsequent collections, skip starts at 0

        if items_to_take <= 0:
            break

    return PatentListResponse(
        total=total_matches,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        items=collected_items
    )


def get_patent(patent_id: str, target_db: Optional[Database] = None) -> PatentResponse:
    """Retrieves a single patent record by its MongoDB ObjectId string."""
    doc, year, _ = find_patent_by_id(patent_id, target_db=target_db)
    return doc_to_patent_response(doc, year)


def create_patent(
    payload: PatentCreateRequest,
    target_db: Optional[Database] = None
) -> PatentResponse:
    """
    Creates a new patent record in the appropriate annual collection.
    Enforces application number uniqueness and publication date year validation.
    """
    database = target_db if target_db is not None else db

    # 1. Validate year from publication_date
    year = resolve_year_from_date(payload.publication_date)

    # 2. Enforce duplicate check on APPLICATION_NUMBER
    check_duplicate_application_number(payload.application_number, target_db=database)

    # 3. Construct document
    now_d_m_y = datetime.now().strftime("%d/%m/%Y")
    doc = {
        "PUBLICATION_NUMBER": payload.publication_number.strip() if payload.publication_number else "",
        "PUBLICATION_DATE": payload.publication_date.strip(),
        "IPO_LOCATION": payload.ipo_location.strip() if payload.ipo_location else "",
        "APPLICATION_TYPE_DESC": payload.application_type_desc.strip() if payload.application_type_desc else "",
        "APPLICATION_NUMBER": payload.application_number.strip(),
        "DATE_OF_FILING": payload.date_of_filing.strip() if payload.date_of_filing else "",
        "TITLE_OF_INVENTION": payload.title_of_invention.strip(),
        "FIELD_OF_INVENTION": payload.field_of_invention.strip() if payload.field_of_invention else "",
        "NO_OF_PAGES": payload.no_of_pages if payload.no_of_pages is not None else 0,
        "NO_OF_CLAIMS": payload.no_of_claims if payload.no_of_claims is not None else 0,
        "DATE_UPDATED_d_m_y": now_d_m_y
    }

    # 4. Insert into the target annual collection
    col_name = f"patents_{year}"
    insert_result = database[col_name].insert_one(doc)
    doc["_id"] = insert_result.inserted_id

    # 5. Synchronize persistent inverted index
    try:
        sync_index_patent_created(doc, year, target_db=database)
    except Exception as exc:
        # Rollback MongoDB insertion to ensure consistency
        database[col_name].delete_one({"_id": doc["_id"]})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to synchronize inverted index for newly created patent: {str(exc)}"
        )

    return doc_to_patent_response(doc, year)


def update_patent(
    patent_id: str,
    payload: PatentUpdateRequest,
    target_db: Optional[Database] = None
) -> PatentResponse:
    """
    Updates an existing patent record.
    Prevents modifying MongoDB _id, enforces APPLICATION_NUMBER uniqueness if altered,
    moves document to new collection if publication year is altered,
    and synchronizes the persistent inverted index with atomic rollback on failure.
    """
    database = target_db if target_db is not None else db
    existing_doc, current_year, current_col_name = find_patent_by_id(patent_id, target_db=database)
    doc_id = existing_doc["_id"]

    # 1. Enforce uniqueness if APPLICATION_NUMBER is being changed
    if payload.application_number is not None:
        new_app_no = payload.application_number.strip()
        if new_app_no != existing_doc.get("APPLICATION_NUMBER"):
            check_duplicate_application_number(new_app_no, exclude_id=doc_id, target_db=database)

    # 2. Check if publication_date changed and resolves to a different supported year
    new_year = current_year
    if payload.publication_date is not None:
        new_year = resolve_year_from_date(payload.publication_date)

    # 3. Assemble updated fields
    now_d_m_y = datetime.now().strftime("%d/%m/%Y")
    update_dict: Dict[str, Any] = {"DATE_UPDATED_d_m_y": now_d_m_y}

    if payload.application_number is not None:
        update_dict["APPLICATION_NUMBER"] = payload.application_number.strip()
    if payload.title_of_invention is not None:
        update_dict["TITLE_OF_INVENTION"] = payload.title_of_invention.strip()
    if payload.publication_date is not None:
        update_dict["PUBLICATION_DATE"] = payload.publication_date.strip()
    if payload.publication_number is not None:
        update_dict["PUBLICATION_NUMBER"] = payload.publication_number.strip()
    if payload.date_of_filing is not None:
        update_dict["DATE_OF_FILING"] = payload.date_of_filing.strip()
    if payload.ipo_location is not None:
        update_dict["IPO_LOCATION"] = payload.ipo_location.strip()
    if payload.application_type_desc is not None:
        update_dict["APPLICATION_TYPE_DESC"] = payload.application_type_desc.strip()
    if payload.field_of_invention is not None:
        update_dict["FIELD_OF_INVENTION"] = payload.field_of_invention.strip()
    if payload.no_of_pages is not None:
        update_dict["NO_OF_PAGES"] = payload.no_of_pages
    if payload.no_of_claims is not None:
        update_dict["NO_OF_CLAIMS"] = payload.no_of_claims

    # 4. Handle intra-collection update vs cross-collection migration with index sync
    if new_year == current_year:
        database[current_col_name].update_one({"_id": doc_id}, {"$set": update_dict})
        updated_doc = {**existing_doc, **update_dict}
        try:
            sync_index_patent_updated(
                existing_doc,
                updated_doc,
                current_year,
                current_year,
                target_db=database
            )
        except Exception as exc:
            # Rollback MongoDB update
            database[current_col_name].replace_one({"_id": doc_id}, existing_doc)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to synchronize inverted index for updated patent: {str(exc)}"
            )
        return doc_to_patent_response(updated_doc, current_year)
    else:
        # Cross-collection migration: delete from old collection, insert into new with same _id
        new_col_name = f"patents_{new_year}"
        merged_doc = {**existing_doc, **update_dict}
        database[current_col_name].delete_one({"_id": doc_id})
        database[new_col_name].insert_one(merged_doc)
        try:
            sync_index_patent_updated(
                existing_doc,
                merged_doc,
                current_year,
                new_year,
                target_db=database
            )
        except Exception as exc:
            # Rollback migration
            database[new_col_name].delete_one({"_id": doc_id})
            database[current_col_name].insert_one(existing_doc)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to synchronize inverted index during patent migration: {str(exc)}"
            )
        return doc_to_patent_response(merged_doc, new_year)


def delete_patent(
    patent_id: str,
    target_db: Optional[Database] = None
) -> PatentDeleteResponse:
    """
    Deletes a patent record from its annual collection and cleans up its postings
    from the persistent inverted index.
    Raises HTTP 404 if not found.
    """
    database = target_db if target_db is not None else db
    existing_doc, current_year, col_name = find_patent_by_id(patent_id, target_db=database)
    doc_id = validate_object_id(patent_id)

    # 1. Synchronize index first: remove all postings for the deleted patent
    sync_index_patent_deleted(existing_doc, current_year, target_db=database)

    # 2. Delete the patent from MongoDB collection
    res = database[col_name].delete_one({"_id": doc_id})
    if res.deleted_count == 0:
        # Restore index postings if MongoDB deletion failed
        try:
            sync_index_patent_created(existing_doc, current_year, target_db=database)
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Patent with ID '{patent_id}' was not found for deletion."
        )

    return PatentDeleteResponse(
        success=True,
        id=patent_id,
        message=f"Patent '{patent_id}' successfully deleted from {col_name}."
    )
