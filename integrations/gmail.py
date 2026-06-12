import os
import base64
import time
from typing import List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

load_dotenv()

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']


def _get_service():
    """Build and return an authenticated Gmail service client."""
    creds = Credentials(
        token=None,
        refresh_token=os.getenv("GOOGLE_REFRESH_TOKEN"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.getenv("GOOGLE_CLIENT_ID"),
        client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
        scopes=SCOPES,
    )
    return build("gmail", "v1", credentials=creds)


def _get_header(headers: list, name: str) -> str:
    """Case-insensitive header lookup."""
    name_lower = name.lower()
    return next(
        (h["value"] for h in headers if h["name"].lower() == name_lower), ""
    )


def _decode_base64(data: str) -> str:
    """
    Decode a base64url string, adding padding only when needed.
    Prevents both 'Incorrect padding' crashes and over-padding valid strings.
    """
    remainder = len(data) % 4
    if remainder:
        data += "=" * (4 - remainder)
    return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")


def _extract_plain_text(payload: dict) -> Optional[str]:
    """
    Recursively extract plain text from a Gmail message payload.
    Prefers text/plain. Falls back to text/html stripped of tags.
    """
    mime_type = payload.get("mimeType", "")

    if mime_type == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            return _decode_base64(data)

    if mime_type == "text/html":
        data = payload.get("body", {}).get("data", "")
        if data:
            html = _decode_base64(data)
            # Strip HTML tags with a simple approach — install beautifulsoup4
            # for better results: pip install beautifulsoup4
            try:
                from bs4 import BeautifulSoup
                return BeautifulSoup(html, "html.parser").get_text(separator=" ")
            except ImportError:
                # Fallback: crude tag stripping
                import re
                return re.sub(r"<[^>]+>", " ", html)

    for part in payload.get("parts", []):
        result = _extract_plain_text(part)
        if result:
            return result

    return None


def _fetch_message_metadata(message_id: str) -> dict:
    """
    Fetch metadata for a single message. Used in thread pool.
    Builds its own service client — the Google API client is NOT
    thread-safe, so each thread needs its own instance.
    """
    service = _get_service()
    detail = service.users().messages().get(
        userId="me",
        id=message_id,
        format="metadata",
        metadataHeaders=["From", "Subject", "Date"],
    ).execute()

    headers = detail.get("payload", {}).get("headers", [])
    return {
        "id": message_id,
        "from": _get_header(headers, "From"),
        "subject": _get_header(headers, "Subject"),
        "received_at": _get_header(headers, "Date"),
        "snippet": detail.get("snippet", ""),
    }


def list_recent_emails(hours_back: int = 24, max_results: int = 100) -> List[dict]:
    """
    Fetch emails from the last N hours.
    Uses a thread pool to fetch metadata concurrently — avoids N+1 slowness.
    Handles pagination via nextPageToken for large inboxes.
    """
    service = _get_service()
    after_timestamp = int(time.time()) - (hours_back * 3600)
    query = f"after:{after_timestamp}"

    # Paginate to collect all message IDs up to max_results
    message_ids = []
    page_token = None

    while len(message_ids) < max_results:
        batch_size = min(500, max_results - len(message_ids))
        params = {
            "userId": "me",
            "q": query,
            "maxResults": batch_size,
        }
        if page_token:
            params["pageToken"] = page_token

        response = service.users().messages().list(**params).execute()
        messages = response.get("messages", [])
        message_ids.extend([m["id"] for m in messages])

        page_token = response.get("nextPageToken")
        if not page_token:
            break

    if not message_ids:
        return []

    # Fetch metadata concurrently using a thread pool
    emails = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {
            executor.submit(_fetch_message_metadata, mid): mid
            for mid in message_ids
        }
        for future in as_completed(futures):
            try:
                emails.append(future.result())
            except Exception as e:
                print(f"[gmail] Failed to fetch message {futures[future]}: {e}")

    return emails


def get_email_body(message_id: str) -> str:
    """
    Fetch the full plain-text body of a single email by ID.
    Falls back to snippet if no text content is found.
    Caps at 5000 chars to control token usage.
    """
    service = _get_service()

    detail = service.users().messages().get(
        userId="me",
        id=message_id,
        format="full",
    ).execute()

    payload = detail.get("payload", {})
    body = _extract_plain_text(payload)

    if body:
        return body[:5000]

    return detail.get("snippet", "")