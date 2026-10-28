import os
from typing import List
from dotenv import load_dotenv

load_dotenv()

class Settings:
    PROJECT_NAME: str = "PatentFind"
    API_V1_STR: str = "/api"
    
    MONGODB_URL: str = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
    DATABASE_NAME: str = os.getenv("DATABASE_NAME", "patentfind")
    
    # Collections to index
    PATENT_YEARS: List[int] = list(range(2016, 2024))
    PATENT_COLLECTIONS: List[str] = [f"patents_{year}" for year in PATENT_YEARS]
    
    # Dedicated collection names
    INVERTED_INDEX_COLLECTION: str = "inverted_index"
    TEMP_INDEX_COLLECTION: str = "inverted_index_temp"
    METADATA_COLLECTION: str = "index_metadata"
    USERS_COLLECTION: str = "users"
    APP_LOCKS_COLLECTION: str = "app_locks"
    
    # Chunking: max postings per MongoDB document to guarantee <16MB
    POSTINGS_CHUNK_SIZE: int = 5000
    
    # Batch size when inserting into MongoDB
    BULK_INSERT_BATCH_SIZE: int = 1000
    
    # CORS
    CORS_ORIGINS: List[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    # JWT & Authentication
    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "patentfind-insecure-dev-secret-key-change-in-production-123456")
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
    ADMIN_SETUP_LOCK_TIMEOUT_SECONDS: int = int(os.getenv("ADMIN_SETUP_LOCK_TIMEOUT_SECONDS", "300"))

settings = Settings()
