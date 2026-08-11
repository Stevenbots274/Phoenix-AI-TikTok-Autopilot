"""Supabase Storage upload boundary for rendered media."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


class StorageError(RuntimeError):
    pass


class MediaStorage:
    def __init__(self):
        self.base_url = os.getenv("SUPABASE_URL", "").rstrip("/")
        self.key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SECRET_KEY", "")
        self.bucket = os.getenv("SUPABASE_STORAGE_BUCKET", "phoenix-media")

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.key)

    def _request(self, method: str, url: str, payload: bytes, content_type: str) -> None:
        request = urllib.request.Request(
            url,
            data=payload,
            method=method,
            headers={
                "apikey": self.key,
                "Authorization": f"Bearer {self.key}",
                "Content-Type": content_type,
                "x-upsert": "true",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30):
                return
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[-300:]
            raise StorageError(f"Supabase Storage returned {error.code}: {detail}") from error

    def _ensure_bucket(self) -> None:
        payload = json.dumps({"id": self.bucket, "name": self.bucket, "public": True}).encode()
        try:
            self._request("POST", f"{self.base_url}/storage/v1/bucket", payload, "application/json")
        except StorageError as error:
            if "409" not in str(error):
                raise
            self._request(
                "PUT",
                f"{self.base_url}/storage/v1/bucket/{urllib.parse.quote(self.bucket, safe='')}",
                json.dumps({"public": True}).encode(),
                "application/json",
            )

    def upload(self, file_path: Path, object_path: str) -> str | None:
        if not self.configured:
            return None
        self._ensure_bucket()
        encoded_path = urllib.parse.quote(object_path, safe="/")
        self._request(
            "POST",
            f"{self.base_url}/storage/v1/object/{urllib.parse.quote(self.bucket, safe='')}/{encoded_path}",
            file_path.read_bytes(),
            "video/mp4",
        )
        return f"{self.base_url}/storage/v1/object/public/{urllib.parse.quote(self.bucket, safe='')}/{encoded_path}"
