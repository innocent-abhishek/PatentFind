#!/usr/bin/env python3
"""
CLI script to securely initialize the first administrator for PatentFind.

Usage:
    # Interactive setup (prompts for username and email if not passed, always masks password):
    python scripts/create_initial_admin.py

    # With optional username and email arguments:
    python scripts/create_initial_admin.py --username admin_master --email admin@patentfind.org

    # Safe recovery if a previous setup process was interrupted:
    python scripts/create_initial_admin.py --reset-lock
"""

import argparse
import getpass
import logging
import os
import sys

# Ensure backend root is in PYTHONPATH so app modules can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.db.mongodb import check_mongodb
from app.services.admin_setup import setup_initial_admin, reset_setup_lock

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("patentfind.cli.admin_setup")


def main():
    parser = argparse.ArgumentParser(
        description="Securely create the initial administrator account for PatentFind."
    )
    parser.add_argument("--username", help="Administrator username (optional)")
    parser.add_argument("--email", help="Administrator email address (optional)")
    parser.add_argument(
        "--reset-lock",
        action="store_true",
        help="Safely clear a stale setup lock from an interrupted attempt (only if no admin exists)"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force reset the lock even if acquired recently (requires verification that no setup process is active)"
    )

    args = parser.parse_args()

    print("=" * 60)
    print(" PatentFind -- Initial Administrator Setup")
    print("=" * 60)

    # 1. Verify MongoDB connectivity
    try:
        check_mongodb()
        print("[+] MongoDB connection verified.")
    except Exception as exc:
        logger.error("Database connection failed during startup: %s", exc)
        print("[-] Error: Unable to connect to the database. Please verify MongoDB is running.", file=sys.stderr)
        sys.exit(1)

    # Handle recovery procedure if --reset-lock is requested
    if args.reset_lock:
        print("\nChecking setup lock status...")
        try:
            cleared = reset_setup_lock(force=args.force)
            if cleared:
                print("[+] Stale setup lock was cleared successfully. You may now run the setup script.")
            else:
                print("[*] No active setup lock found. You may proceed with setup.")
            sys.exit(0)
        except RuntimeError as exc:
            print(f"[-] Lock reset rejected: {exc}", file=sys.stderr)
            if "active setup process" in str(exc):
                print(
                    "[*] Safe Recovery Procedure: Wait for the 5-minute timeout after an interrupted run,\n"
                    "    or add --force (e.g. python scripts/create_initial_admin.py --reset-lock --force)\n"
                    "    only after confirming that no other administrator setup process is currently running.",
                    file=sys.stderr
                )
            sys.exit(1)
        except Exception as exc:
            logger.error("Failed to reset setup lock: %s", exc)
            print("[-] Error: An unexpected database error occurred while resetting the lock.", file=sys.stderr)
            sys.exit(1)

    # 2. Collect username and email
    username = args.username
    if not username:
        try:
            username = input("Enter admin username: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nSetup cancelled.")
            sys.exit(1)

    email = args.email
    if not email:
        try:
            email = input("Enter admin email: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nSetup cancelled.")
            sys.exit(1)

    # 3. Always collect password via getpass (never via CLI arguments)
    try:
        password = getpass.getpass("Enter admin password (min 8 chars): ")
        confirm_password = getpass.getpass("Confirm admin password: ")
    except (KeyboardInterrupt, EOFError):
        print("\nSetup cancelled.")
        sys.exit(1)

    if password != confirm_password:
        print("[-] Error: Passwords do not match.", file=sys.stderr)
        sys.exit(1)

    # 4. Create initial admin safely
    try:
        result = setup_initial_admin(
            username=username,
            email=email,
            password=password
        )
        print("-" * 60)
        print("[+] Initial administrator created successfully!")
        print(f"    ID:       {result['id']}")
        print(f"    Username: {result['username']}")
        print(f"    Email:    {result['email']}")
        print(f"    Role:     {result['role']}")
        print(f"    Created:  {result['created_at']}")
        print("=" * 60)
    except RuntimeError as exc:
        # Expected domain rule validation (e.g. admin exists, invalid input, duplicate user)
        print(f"[-] Setup rejected: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        # Unexpected errors: log safely without leaking credentials, show safe terminal error
        logger.error("Unexpected error during administrator setup: %s", exc)
        print(
            "[-] Error: An unexpected error occurred while creating the administrator. "
            "Please check the server logs for diagnostic details.",
            file=sys.stderr
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
