"""Restore the demo account to its seeded state.

    uv run --env-file .env python reset_demo.py

Deletes every document the demo user has (rows and files), then uploads the five files in
data/demo/account and runs each one through the real pipeline, oldest first. Creates the
user if it doesn't exist and resets its password. Needs DEMO_EMAIL and DEMO_PASSWORD on top
of the API settings. Extractions are cached under .cache/gemini, so later resets give the
same record. Exits 1 if a document fails or a planted conflict is missing.
"""

import json
import mimetypes
import os
import sys
from pathlib import Path

from app.db import BUCKET, rows, supabase
from app.documents import save_document
from app.pipeline.run import process_document
from app.record import build_record

DEMO_DIR = Path(__file__).resolve().parent.parent / "data" / "demo"


def demo_user_id(email: str, password: str) -> str:
    admin = supabase().auth.admin
    page = 1
    while users := admin.list_users(page=page, per_page=1000):
        for user in users:
            if user.email == email:
                admin.update_user_by_id(user.id, {"password": password})
                return user.id
        page += 1
    created = admin.create_user(
        {"email": email, "password": password, "email_confirm": True}
    )
    return created.user.id


def storage_files(prefix: str) -> list[str]:
    """Every object under prefix. Folders come back from list() without an id."""
    found = []
    for entry in supabase().storage.from_(BUCKET).list(prefix, {"limit": 1000}):
        path = f"{prefix}/{entry['name']}"
        found.extend([path] if entry.get("id") else storage_files(path))
    return found


def clear(user_id: str) -> None:
    paths = storage_files(user_id)
    if paths:
        supabase().storage.from_(BUCKET).remove(paths)
    supabase().table("documents").delete().eq("user_id", user_id).execute()
    print(f"Removed {len(paths)} stored files and the documents rows")


def seed(user_id: str) -> bool:
    ok = True
    for path in sorted(DEMO_DIR.glob("account/*")):
        content_type = mimetypes.guess_type(path.name)[0] or ""
        row = save_document(user_id, path.name, content_type, path.read_bytes())
        process_document(row["id"])
        done = rows(
            supabase()
            .table("documents")
            .select("status, error")
            .eq("id", row["id"])
            .execute()
        )[0]
        print(f"  {path.name}: {done['status']} {done['error'] or ''}")
        ok = ok and done["status"] == "done"
    return ok


def check(user_id: str) -> bool:
    """Every conflict planted in ground_truth.json shows up in the record."""
    record = build_record(
        rows(
            supabase()
            .table("documents")
            .select("id, filename, extraction")
            .eq("user_id", user_id)
            .eq("status", "done")
            .order("created_at")
            .execute()
        )
    )
    counts = ", ".join(
        f"{len(record[s])} {s}"
        for s in ("medications", "allergies", "conditions", "labs")
    )
    print(f"Record: {counts}")
    found = {(c["kind"], c["name"].casefold()) for c in record["conflicts"]}
    for conflict in record["conflicts"]:
        values = " vs ".join(v["value"] for v in conflict["variants"])
        print(f"  conflict {conflict['kind']}: {conflict['name']} ({values})")
    expected = json.loads((DEMO_DIR / "ground_truth.json").read_text())
    missing = [
        c
        for c in expected["expected_conflicts"]
        if not any(
            kind == c["kind"] and c["name"].casefold() in name for kind, name in found
        )
    ]
    for conflict in missing:
        print(f"  MISSING {conflict['kind']}: {conflict['name']}")
    return not missing


def main() -> None:
    user_id = demo_user_id(os.environ["DEMO_EMAIL"], os.environ["DEMO_PASSWORD"])
    print(f"Demo user {os.environ['DEMO_EMAIL']} ({user_id})")
    clear(user_id)
    seeded = seed(user_id)
    if not (check(user_id) and seeded):
        sys.exit(1)
    print("Demo account ready")


if __name__ == "__main__":
    main()
