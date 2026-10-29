import logging
from typing import Optional
from fastapi import APIRouter, Depends, File, Query, UploadFile, status

from app.api.deps import require_admin
from app.schemas.admin_patents import (
    PatentCreateRequest,
    PatentUpdateRequest,
    PatentResponse,
    PatentListResponse,
    PatentDeleteResponse,
    CsvImportSummaryResponse
)
from app.services import admin_patent_service
from app.services.csv_import_service import process_csv_upload

logger = logging.getLogger("patentfind.api.admin_patents")
router = APIRouter(prefix="/admin/patents", tags=["Admin Patent Management"])


@router.get(
    "",
    response_model=PatentListResponse,
    status_code=status.HTTP_200_OK,
    summary="List patent records with pagination and filters (Admin only)"
)
def list_patents(
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(10, ge=1, le=100, description="Items per page"),
    q: Optional[str] = Query(None, description="Search query across title, application number, or field"),
    ipo_location: Optional[str] = Query(None, description="Filter by IPO location"),
    field_of_invention: Optional[str] = Query(None, description="Filter by field of invention"),
    year: Optional[int] = Query(None, description="Filter by specific collection year (2016-2023)"),
    admin_claims: dict = Depends(require_admin)
) -> PatentListResponse:
    """
    Retrieves a paginated list of patents across annual collections.
    Supports filtering by text query, IPO location, field of invention, and year.
    Requires administrator role.
    """
    logger.info("Admin '%s' requested patent list (page=%d, page_size=%d, q=%s)", admin_claims.get("username"), page, page_size, q)
    return admin_patent_service.list_patents(
        page=page,
        page_size=page_size,
        q=q,
        ipo_location=ipo_location,
        field_of_invention=field_of_invention,
        year=year
    )


@router.get(
    "/{patent_id}",
    response_model=PatentResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve individual patent details by ID (Admin only)"
)
def get_patent(
    patent_id: str,
    admin_claims: dict = Depends(require_admin)
) -> PatentResponse:
    """
    Retrieves full details for a single patent record by its MongoDB ObjectId.
    Searches across annual collections patents_2016 through patents_2023.
    Requires administrator role.
    """
    logger.info("Admin '%s' requested patent details for ID '%s'", admin_claims.get("username"), patent_id)
    return admin_patent_service.get_patent(patent_id)


@router.post(
    "",
    response_model=PatentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new patent record (Admin only)"
)
def create_patent(
    payload: PatentCreateRequest,
    admin_claims: dict = Depends(require_admin)
) -> PatentResponse:
    """
    Creates a new patent record in the appropriate annual collection based on publication_date.
    Validates date formats, checks APPLICATION_NUMBER uniqueness across all collections,
    and returns the created patent with its generated MongoDB ObjectId.
    Requires administrator role.
    """
    logger.info("Admin '%s' creating new patent '%s'", admin_claims.get("username"), payload.application_number)
    return admin_patent_service.create_patent(payload)


@router.put(
    "/{patent_id}",
    response_model=PatentResponse,
    status_code=status.HTTP_200_OK,
    summary="Update an existing patent record (Admin only)"
)
def update_patent(
    patent_id: str,
    payload: PatentUpdateRequest,
    admin_claims: dict = Depends(require_admin)
) -> PatentResponse:
    """
    Updates an existing patent record located across annual collections.
    Preserves MongoDB _id, enforces uniqueness if APPLICATION_NUMBER is altered,
    and safely migrates document if publication year changed.
    Requires administrator role.
    """
    logger.info("Admin '%s' updating patent '%s'", admin_claims.get("username"), patent_id)
    return admin_patent_service.update_patent(patent_id, payload)


@router.delete(
    "/{patent_id}",
    response_model=PatentDeleteResponse,
    status_code=status.HTTP_200_OK,
    summary="Delete a patent record (Admin only)"
)
def delete_patent(
    patent_id: str,
    admin_claims: dict = Depends(require_admin)
) -> PatentDeleteResponse:
    """
    Deletes a patent record from its annual collection after confirmation.
    Requires administrator role.
    """
    logger.info("Admin '%s' deleting patent '%s'", admin_claims.get("username"), patent_id)
    return admin_patent_service.delete_patent(patent_id)


@router.post(
    "/upload-csv",
    response_model=CsvImportSummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="Batch import patent records from CSV (Admin only)"
)
async def upload_csv(
    file: UploadFile = File(..., description="CSV file containing patent records"),
    admin_claims: dict = Depends(require_admin)
) -> CsvImportSummaryResponse:
    """
    Imports patent records in batch from a CSV file.
    Validates required columns, date formats, numeric values, and duplicate application numbers.
    Batch inserts valid records into their corresponding annual collections and synchronizes
    the persistent inverted index.
    Requires administrator role.
    """
    logger.info("Admin '%s' uploaded CSV file '%s'", admin_claims.get("username"), file.filename)
    return await process_csv_upload(file)
