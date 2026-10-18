import os
from functools import lru_cache
from typing import Any, cast

from postgrest import APIResponse
from supabase import Client, create_client

BUCKET = "documents"

Row = dict[str, Any]


@lru_cache
def supabase() -> Client:
    """Secret-key client. It bypasses RLS, so every query must filter by user_id."""
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])


def rows(response: APIResponse) -> list[Row]:
    """The rows a query returned. supabase-py types them as any JSON value; ours are objects."""
    return cast(list[Row], response.data)
