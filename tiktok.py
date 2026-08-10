"""Small TikTok Content Posting API boundary. Tokens never belong in frontend code."""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request


class TikTokConfigurationError(RuntimeError):
    pass


class TikTokClient:
    authorize_url = "https://www.tiktok.com/v2/auth/authorize/"
    token_url = "https://open.tiktokapis.com/v2/oauth/token/"
    publish_url = "https://open.tiktokapis.com/v2/post/publish/video/init/"

    def __init__(self):
        self.client_key = os.getenv("TIKTOK_CLIENT_KEY", "")
        self.client_secret = os.getenv("TIKTOK_CLIENT_SECRET", "")
        self.redirect_uri = os.getenv(
            "TIKTOK_REDIRECT_URI", "http://localhost:8000/api/tiktok/oauth/callback"
        )
        self.scopes = os.getenv("TIKTOK_SCOPES", "user.info.basic,video.publish")

    @property
    def configured(self) -> bool:
        return bool(self.client_key and self.client_secret and self.redirect_uri)

    def authorization_url(self, state: str) -> str:
        if not self.configured:
            raise TikTokConfigurationError(
                "TikTok is not configured. Add TIKTOK_CLIENT_KEY and TIKTOK_CLIENT_SECRET."
            )
        params = urllib.parse.urlencode(
            {
                "client_key": self.client_key,
                "response_type": "code",
                "scope": self.scopes,
                "redirect_uri": self.redirect_uri,
                "state": state,
            }
        )
        return f"{self.authorize_url}?{params}"

    def exchange_code(self, code: str) -> dict:
        if not self.configured:
            raise TikTokConfigurationError("TikTok credentials are not configured.")
        payload = urllib.parse.urlencode(
            {
                "client_key": self.client_key,
                "client_secret": self.client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": self.redirect_uri,
            }
        ).encode()
        request = urllib.request.Request(
            self.token_url, data=payload, headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            data = json.loads(response.read().decode())
        if data.get("error"):
            raise TikTokConfigurationError(data.get("error_description", data["error"]))
        return data

    def refresh_access_token(self, refresh_token: str) -> dict:
        if not self.configured:
            raise TikTokConfigurationError("TikTok credentials are not configured.")
        payload = urllib.parse.urlencode(
            {
                "client_key": self.client_key,
                "client_secret": self.client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            }
        ).encode()
        request = urllib.request.Request(
            self.token_url, data=payload, headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode())

    def initialize_video_post(self, access_token: str, video_url: str, caption: str) -> dict:
        """Initialize a pull-from-URL post; the URL must be publicly reachable by TikTok."""
        if not access_token:
            raise TikTokConfigurationError("A TikTok access token is required to publish.")
        payload = json.dumps(
            {
                "post_info": {"title": caption[:150], "privacy_level": "PUBLIC_TO_EVERYONE", "disable_comment": False},
                "source_info": {"source": "PULL_FROM_URL", "video_url": video_url},
            }
        ).encode()
        request = urllib.request.Request(
            self.publish_url,
            data=payload,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {access_token}"},
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode())
