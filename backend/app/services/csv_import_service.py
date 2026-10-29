import csv
import io
import logging
import re
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple, Any
from fastapi import HTTPException, UploadFile, status
from pymongo.database import Database

from app.core.config import settings
from app.db.mongodb import db
from app.indexing.index_sync import sync_index_patent_created
from app.schemas.admin_patents import (
    CsvImportSummaryResponse,
    SkippedDuplicateItem,
    ValidationErrorItem
)

logger = logging.getLogger("patentfind.csv_import")

DATE_PATTERN = re.compile(r"^\d{2}/\d{2}/\d{4}$")

REQUIRED_COLUMN_KEYS = {"APPLICATION_NUMBER", "TITLE_OF_INVENTION", "PUBLICATION_DATE"}

COLUMN_KEY_MAP = {
    "PUBLICATION_NUMBER": "PUBLICATION_NUMBER",
    "PUBLICATION_DATE": "PUBLICATION_DATE",
    "IPO_LOCATION": "IPO_LOCATION",
    "APPLICATION_TYPE_DESC": "APPLICATION_TYPE_DESC",
    "APPLICATION_NUMBER": "APPLICATION_NUMBER",
    "DATE_OF_FILING": "DATE_OF_FILING",
    "TITLE_OF_INVENTION": "TITLE_OF_INVENTION",
    "FIELD_OF_INVENTION": "FIELD_OF_INVENTION",
    "NO_OF_PAGES": "NO_OF_PAGES",
    "NO_OF_CLAIMS": "NO_OF_CLAIMS",
    "DATE_UPDATED_D_M_Y": "DATE_UPDATED_d_m_y",
    "DATE_UPDATED": "DATE_UPDATED_d_m_y",
}


def normalize_header(header: str) -> str:
    """Normalizes a CSV header string to standardized uppercase format."""
    clean = header.strip().lstrip("\ufeff").strip('"').strip("'")
    clean = re.sub(r"[\s\-]+", "_", clean).upper()
    return clean


def parse_and_validate_date(date_str: str, field_name: str, row_num: int) -> Tuple[Optional[str], Optional[int], Optional[str]]:
    """
    Validates that a date string is in DD/MM/YYYY format and is a real calendar date.
    Returns (cleaned_date, year, error_message).
    """
    if not date_str or not date_str.strip():
        return None, None, f"{field_name} is required."
    clean = date_str.strip()
    if not DATE_PATTERN.match(clean):
        return None, None, f"{field_name} '{clean}' must be in DD/MM/YYYY format."
    try:
        dt = datetime.strptime(clean, "%d/%m/%Y")
        return clean, dt.year, None
    except ValueError:
        return None, None, f"{field_name} '{clean}' is not a valid calendar date."


def parse_int_field(val: Optional[str], field_name: str, row_num: int, default: int = 0) -> Tuple[int, Optional[str]]:
    """Parses and validates a non-negative integer field."""
    if val is None or not val.strip():
        return default, None
    clean = val.strip()
    try:
        num = int(float(clean))
        if num < 0:
            return 0, f"{field_name} must be a non-negative integer (got '{clean}')."
        return num, None
    except (ValueError, TypeError):
        return 0, f"{field_name} must be a valid integer (got '{clean}')."


async def process_csv_upload(
    file: UploadFile,
    target_db: Optional[Database] = None
) -> CsvImportSummaryResponse:
    """
    Validates, deduplicates, batch-inserts, and synchronizes inverted index for patent records
    imported from a CSV file.
    """
    database = target_db if target_db is not None else db

    # 1. Validate file extension and MIME type
    filename = file.filename or ""
    if not filename.lower().endswith(".csv"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file format. Please upload a valid .csv file."
        )

    # 2. Read file content with bounded memory check
    content_chunks = []
    total_bytes = 0
    max_bytes = settings.MAX_CSV_UPLOAD_BYTES

    try:
        while True:
            chunk = await file.read(64 * 1024)  # 64 KB chunks
            if not chunk:
                break
            total_bytes += len(chunk)
            if total_bytes > max_bytes:
                max_mb = max_bytes / (1024 * 1024)
                raise HTTPException(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    detail=f"CSV file size exceeds the maximum allowed limit of {max_mb:.1f} MB."
                )
            content_chunks.append(chunk)
    finally:
        await file.close()

    raw_bytes = b"".join(content_chunks)
    if not raw_bytes or not raw_bytes.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The uploaded CSV file is empty."
        )

    # 3. Decode safely (try utf-8-sig first to strip BOM, then utf-8, then latin-1)
    text = None
    for encoding in ["utf-8-sig", "utf-8", "latin-1"]:
        try:
            text = raw_bytes.decode(encoding)
            break
        except UnicodeDecodeError:
            continue

    if text is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unable to decode CSV file. Please ensure the file is encoded in UTF-8."
        )

    # 4. Stream and validate CSV headers
    csv_file = io.StringIO(text)
    reader = csv.reader(csv_file)

    try:
        raw_header = next(reader)
    except StopIteration:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The uploaded CSV file contains no headers or data."
        )

    header_indices: Dict[str, int] = {}
    for idx, col in enumerate(raw_header):
        norm = normalize_header(col)
        standard_name = COLUMN_KEY_MAP.get(norm, norm)
        header_indices[standard_name] = idx

    missing_required = REQUIRED_COLUMN_KEYS - set(header_indices.keys())
    if missing_required:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Missing required CSV column headers: {sorted(list(missing_required))}. "
                f"Required headers are: {sorted(list(REQUIRED_COLUMN_KEYS))}."
            )
        )

    # 5. Row-level validation and in-file duplicate detection
    validation_errors: List[ValidationErrorItem] = []
    skipped_duplicates: List[SkippedDuplicateItem] = []
    candidate_rows: List[Dict[str, Any]] = []
    seen_in_file_app_nums: Set[str] = set()

    total_data_rows = 0
    now_d_m_y = datetime.now().strftime("%d/%m/%Y")

    for row_idx, row in enumerate(reader, start=2):  # row 1 is header, data rows start at row 2
        # Check if row is completely empty
        if not row or not any(cell.strip() for cell in row):
            continue

        total_data_rows += 1
        if total_data_rows > settings.MAX_CSV_ROWS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"CSV file exceeds the maximum allowed limit of {settings.MAX_CSV_ROWS:,} data rows."
            )

        def get_val(key: str) -> str:
            idx = header_indices.get(key)
            if idx is not None and idx < len(row):
                return row[idx].strip()
            return ""

        row_errors: List[str] = []

        # Validate APPLICATION_NUMBER
        app_num = get_val("APPLICATION_NUMBER")
        if not app_num:
            validation_errors.append(ValidationErrorItem(
                row=row_idx,
                field="APPLICATION_NUMBER",
                message="Application Number is required and cannot be empty."
            ))
            row_errors.append("APPLICATION_NUMBER missing")

        # Validate TITLE_OF_INVENTION
        title = get_val("TITLE_OF_INVENTION")
        if not title:
            validation_errors.append(ValidationErrorItem(
                row=row_idx,
                field="TITLE_OF_INVENTION",
                message="Title of Invention is required and cannot be empty."
            ))
            row_errors.append("TITLE_OF_INVENTION missing")

        # Validate PUBLICATION_DATE & Year
        pub_date_raw = get_val("PUBLICATION_DATE")
        pub_date, pub_year, pub_err = parse_and_validate_date(pub_date_raw, "PUBLICATION_DATE", row_idx)
        if pub_err:
            validation_errors.append(ValidationErrorItem(
                row=row_idx,
                field="PUBLICATION_DATE",
                message=pub_err
            ))
            row_errors.append("PUBLICATION_DATE invalid")
        elif pub_year not in settings.PATENT_YEARS:
            min_yr = min(settings.PATENT_YEARS)
            max_yr = max(settings.PATENT_YEARS)
            validation_errors.append(ValidationErrorItem(
                row=row_idx,
                field="PUBLICATION_DATE",
                message=f"Publication year '{pub_year}' is outside supported collection range ({min_yr}-{max_yr})."
            ))
            row_errors.append("PUBLICATION_DATE year unsupported")

        # Validate DATE_OF_FILING (optional)
        filing_date_raw = get_val("DATE_OF_FILING")
        filing_date = None
        if filing_date_raw:
            filing_date, _, filing_err = parse_and_validate_date(filing_date_raw, "DATE_OF_FILING", row_idx)
            if filing_err:
                validation_errors.append(ValidationErrorItem(
                    row=row_idx,
                    field="DATE_OF_FILING",
                    message=filing_err
                ))
                row_errors.append("DATE_OF_FILING invalid")

        # Validate numeric fields
        no_pages, pages_err = parse_int_field(get_val("NO_OF_PAGES"), "NO_OF_PAGES", row_idx, default=0)
        if pages_err:
            validation_errors.append(ValidationErrorItem(
                row=row_idx,
                field="NO_OF_PAGES",
                message=pages_err
            ))
            row_errors.append("NO_OF_PAGES invalid")

        no_claims, claims_err = parse_int_field(get_val("NO_OF_CLAIMS"), "NO_OF_CLAIMS", row_idx, default=0)
        if claims_err:
            validation_errors.append(ValidationErrorItem(
                row=row_idx,
                field="NO_OF_CLAIMS",
                message=claims_err
            ))
            row_errors.append("NO_OF_CLAIMS invalid")

        if row_errors:
            continue

        # Check in-file duplicate APPLICATION_NUMBER
        if app_num in seen_in_file_app_nums:
            skipped_duplicates.append(SkippedDuplicateItem(
                row=row_idx,
                application_number=app_num,
                reason=f"Duplicate Application Number '{app_num}' found multiple times within this CSV file."
            ))
            continue

        seen_in_file_app_nums.add(app_num)

        # Assemble candidate document
        candidate_doc = {
            "row_num": row_idx,
            "year": pub_year,
            "doc": {
                "PUBLICATION_NUMBER": get_val("PUBLICATION_NUMBER"),
                "PUBLICATION_DATE": pub_date,
                "IPO_LOCATION": get_val("IPO_LOCATION"),
                "APPLICATION_TYPE_DESC": get_val("APPLICATION_TYPE_DESC"),
                "APPLICATION_NUMBER": app_num,
                "DATE_OF_FILING": filing_date or "",
                "TITLE_OF_INVENTION": title,
                "FIELD_OF_INVENTION": get_val("FIELD_OF_INVENTION"),
                "NO_OF_PAGES": no_pages,
                "NO_OF_CLAIMS": no_claims,
                "DATE_UPDATED_d_m_y": get_val("DATE_UPDATED_d_m_y") or now_d_m_y,
            }
        }
        candidate_rows.append(candidate_doc)

    # 6. Database duplicate detection across all candidate rows
    ready_to_insert: List[Dict[str, Any]] = []

    if candidate_rows:
        candidate_app_numbers = [item["doc"]["APPLICATION_NUMBER"] for item in candidate_rows]
        existing_app_numbers_map: Dict[str, str] = {}

        # Query existing patent collections in batch
        for yr in settings.PATENT_YEARS:
            col_name = f"patents_{yr}"
            cursor = database[col_name].find(
                {"APPLICATION_NUMBER": {"$in": candidate_app_numbers}},
                {"APPLICATION_NUMBER": 1}
            )
            for record in cursor:
                app_no = record.get("APPLICATION_NUMBER")
                if app_no:
                    existing_app_numbers_map[app_no] = col_name

        for item in candidate_rows:
            app_no = item["doc"]["APPLICATION_NUMBER"]
            if app_no in existing_app_numbers_map:
                existing_col = existing_app_numbers_map[app_no]
                skipped_duplicates.append(SkippedDuplicateItem(
                    row=item["row_num"],
                    application_number=app_no,
                    reason=f"Patent with Application Number '{app_no}' already exists in database collection {existing_col}."
                ))
            else:
                ready_to_insert.append(item)

    # 7. Batch insertion and index synchronization by year collection
    imported_count = 0
    docs_by_year: Dict[int, List[Dict[str, Any]]] = {}
    for item in ready_to_insert:
        yr = item["year"]
        docs_by_year.setdefault(yr, []).append(item["doc"])

    for yr, docs in docs_by_year.items():
        if not docs:
            continue
        col_name = f"patents_{yr}"
        try:
            insert_result = database[col_name].insert_many(docs, ordered=False)
            inserted_ids = insert_result.inserted_ids

            # Associate generated _id and synchronize persistent inverted index
            for idx, doc in enumerate(docs):
                doc["_id"] = inserted_ids[idx]
                try:
                    sync_index_patent_created(doc, yr, target_db=database)
                    imported_count += 1
                except Exception as sync_exc:
                    logger.error(
                        "Index sync failed for imported patent %s (App: %s): %s",
                        doc["_id"], doc.get("APPLICATION_NUMBER"), sync_exc
                    )
                    # Compensating rollback: delete un-indexed doc
                    database[col_name].delete_one({"_id": doc["_id"]})
                    validation_errors.append(ValidationErrorItem(
                        row=0,
                        field="INDEX_SYNC",
                        message=f"Index synchronization failed for '{doc.get('APPLICATION_NUMBER')}': {str(sync_exc)}"
                    ))

        except Exception as insert_exc:
            logger.error("Batch insertion failed for collection %s: %s", col_name, insert_exc)
            validation_errors.append(ValidationErrorItem(
                row=0,
                field="BATCH_INSERT",
                message=f"Database batch insertion failed for year {yr}: {str(insert_exc)}"
            ))

    duplicate_count = len(skipped_duplicates)
    failed_count = len(validation_errors)

    summary_message = (
        f"CSV processing completed. Evaluated {total_data_rows} rows: "
        f"{imported_count} imported successfully, "
        f"{duplicate_count} duplicate rows skipped, "
        f"{failed_count} errors."
    )

    return CsvImportSummaryResponse(
        success=(imported_count > 0 or (total_data_rows == 0 and failed_count == 0)),
        total_rows=total_data_rows,
        imported_count=imported_count,
        duplicate_count=duplicate_count,
        failed_count=failed_count,
        skipped_duplicates=skipped_duplicates,
        validation_errors=validation_errors,
        message=summary_message
    )
