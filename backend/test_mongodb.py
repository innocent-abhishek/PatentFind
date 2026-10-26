
from app.db.mongodb import client, db, check_mongodb

try:
    if check_mongodb():
        print("MongoDB connected successfully!")
        print("Database:", db.name)

        collections = db.list_collection_names()
        print("Collections found:", len(collections))

        for name in sorted(collections):
            print("-", name)

        for year in range(2016, 2024):
            collection = db[f"patents_{year}"]
            print(f"\nYear: {year}")
            print("Document count:", collection.count_documents({}))

            sample = collection.find_one()
            if sample:
                print("Fields:", list(sample.keys()))

finally:
    client.close()

