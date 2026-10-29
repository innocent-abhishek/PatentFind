from typing import List, Optional
from pydantic import BaseModel, Field, field_validator
import re
from datetime import datetime


DATE_PATTERN = re.compile(r"^\d{2}/\d{2}/\d{4}$")


def validate_date_format(val: Optional[str], field_name: str) -> Optional[str]:
    """Validates that a date string matches DD/MM/YYYY and is a real calendar date."""
    if val is None or not val.strip():
        return None
    val = val.strip()
    if not DATE_PATTERN.match(val):
        raise ValueError(f"{field_name} must be in DD/MM/YYYY format.")
    try:
        datetime.strptime(val, "%d/%m/%Y")
    except ValueError:
        raise ValueError(f"{field_name} is not a valid calendar date.")
    return val


class PatentCreateRequest(BaseModel):
    application_number: str = Field(..., description="Unique application number (e.g. 1003/DELNP/2009)")
    title_of_invention: str = Field(..., description="Title of invention")
    publication_date: str = Field(..., description="Publication date in DD/MM/YYYY format")
    publication_number: Optional[str] = Field(None, description="Publication gazette number (e.g. 01/2023)")
    date_of_filing: Optional[str] = Field(None, description="Filing date in DD/MM/YYYY format")
    ipo_location: Optional[str] = Field(None, description="IPO location (e.g. Delhi, Mumbai, Chennai, Kolkata)")
    application_type_desc: Optional[str] = Field(None, description="Application classification description")
    field_of_invention: Optional[str] = Field(None, description="Field of invention (e.g. FOOD, CHEMISTRY)")
    no_of_pages: Optional[int] = Field(None, ge=0, description="Total pages (must be non-negative)")
    no_of_claims: Optional[int] = Field(None, ge=0, description="Number of claims (must be non-negative)")

    @field_validator("application_number")
    @classmethod
    def validate_app_number(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Application number is required and cannot be empty.")
        return v.strip()

    @field_validator("title_of_invention")
    @classmethod
    def validate_title(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Title of invention is required and cannot be empty.")
        return v.strip()

    @field_validator("publication_date")
    @classmethod
    def validate_pub_date(cls, v: str) -> str:
        res = validate_date_format(v, "publication_date")
        if not res:
            raise ValueError("Publication date is required.")
        return res

    @field_validator("date_of_filing")
    @classmethod
    def validate_filing_date(cls, v: Optional[str]) -> Optional[str]:
        return validate_date_format(v, "date_of_filing")


class PatentUpdateRequest(BaseModel):
    application_number: Optional[str] = Field(None, description="Updated unique application number")
    title_of_invention: Optional[str] = Field(None, description="Updated title of invention")
    publication_date: Optional[str] = Field(None, description="Updated publication date in DD/MM/YYYY format")
    publication_number: Optional[str] = Field(None, description="Updated publication number")
    date_of_filing: Optional[str] = Field(None, description="Updated filing date in DD/MM/YYYY format")
    ipo_location: Optional[str] = Field(None, description="Updated IPO location")
    application_type_desc: Optional[str] = Field(None, description="Updated application classification")
    field_of_invention: Optional[str] = Field(None, description="Updated field of invention")
    no_of_pages: Optional[int] = Field(None, ge=0, description="Updated number of pages")
    no_of_claims: Optional[int] = Field(None, ge=0, description="Updated number of claims")

    @field_validator("application_number")
    @classmethod
    def validate_app_number(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            if not v.strip():
                raise ValueError("Application number cannot be empty if provided.")
            return v.strip()
        return None

    @field_validator("title_of_invention")
    @classmethod
    def validate_title(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            if not v.strip():
                raise ValueError("Title of invention cannot be empty if provided.")
            return v.strip()
        return None

    @field_validator("publication_date")
    @classmethod
    def validate_pub_date(cls, v: Optional[str]) -> Optional[str]:
        return validate_date_format(v, "publication_date")

    @field_validator("date_of_filing")
    @classmethod
    def validate_filing_date(cls, v: Optional[str]) -> Optional[str]:
        return validate_date_format(v, "date_of_filing")


class PatentResponse(BaseModel):
    id: str = Field(..., description="Unique 24-char hex MongoDB ObjectId string")
    year: int = Field(..., description="Year of the patent collection (e.g. 2023)")
    collection: str = Field(..., description="MongoDB collection name (e.g. patents_2023)")
    application_number: str = Field(..., description="Primary business identifier")
    publication_number: Optional[str] = Field(None, description="Publication gazette number")
    publication_date: Optional[str] = Field(None, description="Publication date in DD/MM/YYYY format")
    date_of_filing: Optional[str] = Field(None, description="Filing date in DD/MM/YYYY format")
    ipo_location: Optional[str] = Field(None, description="IPO location")
    application_type_desc: Optional[str] = Field(None, description="Application classification")
    title_of_invention: Optional[str] = Field(None, description="Title of invention")
    field_of_invention: Optional[str] = Field(None, description="Field of invention")
    no_of_pages: Optional[int] = Field(None, description="Total pages")
    no_of_claims: Optional[int] = Field(None, description="Number of claims")
    date_updated_d_m_y: Optional[str] = Field(None, description="Last updated date in DD/MM/YYYY format")


class PatentListResponse(BaseModel):
    total: int = Field(..., description="Total matching patents across queried collections")
    page: int = Field(..., description="Current page number (1-based)")
    page_size: int = Field(..., description="Number of items per page")
    total_pages: int = Field(..., description="Total available pages")
    items: List[PatentResponse] = Field(default_factory=list, description="List of patents for current page")


class PatentDeleteResponse(BaseModel):
    success: bool = Field(True, description="Indicates whether the deletion succeeded")
    id: str = Field(..., description="Deleted patent ObjectId string")
    message: str = Field(..., description="Status message")


class SkippedDuplicateItem(BaseModel):
    row: int = Field(..., description="Row number in the uploaded CSV file (1-based data row)")
    application_number: str = Field(..., description="Application number that caused the duplicate collision")
    reason: str = Field(..., description="Detailed duplicate collision reason")


class ValidationErrorItem(BaseModel):
    row: int = Field(..., description="Row number in the uploaded CSV file (1-based data row)")
    field: str = Field(..., description="Column/field name that failed validation")
    message: str = Field(..., description="Detailed validation error message")


class CsvImportSummaryResponse(BaseModel):
    success: bool = Field(..., description="Overall import operation status")
    total_rows: int = Field(..., description="Total non-empty data rows evaluated in CSV")
    imported_count: int = Field(..., description="Total patent records successfully inserted and indexed")
    duplicate_count: int = Field(..., description="Total duplicate records skipped")
    failed_count: int = Field(..., description="Total rows that failed validation or insertion")
    skipped_duplicates: List[SkippedDuplicateItem] = Field(default_factory=list, description="List of skipped duplicate records with row numbers")
    validation_errors: List[ValidationErrorItem] = Field(default_factory=list, description="List of row-level validation errors")
    message: str = Field(..., description="High-level import summary narrative")
