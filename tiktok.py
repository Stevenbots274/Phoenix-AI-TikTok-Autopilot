"""Small TikTok Content Posting API boundary. Tokens never belong in frontend code."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request


class TikTokConfigurationError(RuntimeError):
    pass


class TikTokClient:
    authorize_url = "https://www.tiktok.com/v2/auth/authorize/"
    token_url = "https://open.tiktokapis.com/v2/oauth/token/"
    creator_info_url = "https://open.tiktokapis.com/v2/post/publish/creator_info/query/"
    publish_url = "https://open.tiktokapis.com/v2/post/publish/video/init/"
    publish_status_url = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"

    def __init__(self):
        self.client_key = os.getenv("TIKTOK_CLIENT_KEY", "")
        self.client_secret = os.getenv("TIKTOK_CLIENT_SECRET", "")
        self.redirect_uri = os.getenv(
            "TIKTOK_REDIRECT_URI",
            "https://tiktok.senseiphoenix.name.ng/api/tiktok/oauth/callback",
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
        data = self._json_request(request, 15)
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
        return self._json_request(request, 15)

    def initialize_video_post(self, access_token: str, video_url: str, caption: str) -> dict:
        """Initialize a pull-from-URL post; the URL must be publicly reachable by TikTok."""
        if not access_token:
            raise TikTokConfigurationError("A TikTok access token is required to publish.")
        creator_info = self.creator_info(access_token)
        allowed_privacy = creator_info.get("privacy_level_options", [])
        privacy_level = allowed_privacy[0] if allowed_privacy else "SELF_ONLY"
        payload = json.dumps(
            {
                "post_info": {
                    "title": caption[:150],
                    "privacy_level": privacy_level,
                    "disable_comment": False,
                },
                "source_info": {"source": "PULL_FROM_URL", "video_url": video_url},
            }
        ).encode()
        request = urllib.request.Request(
            self.publish_url,
            data=payload,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {access_token}"},
        )
        return self._json_request(request, 20)

    def creator_info(self, access_token: str) -> dict:
        """Query TikTok before posting so privacy and duration follow creator settings."""
        if not access_token:
            raise TikTokConfigurationError("A TikTok access token is required.")
        request = urllib.request.Request(
            self.creator_info_url,
            data=b"{}",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {access_token}"},
        )
        data = self._json_request(request, 15)
        if data.get("error", {}).get("code") not in (None, "ok"):
            raise TikTokConfigurationError(data["error"].get("message", "TikTok creator settings failed"))
        return data.get("data", data)

    def publish_status(self, access_token: str, publish_id: str) -> dict:
        if not access_token or not publish_id:
            raise TikTokConfigurationError("TikTok publish status needs an access token and publish ID.")
        request = urllib.request.Request(
            self.publish_status_url,
            data=json.dumps({"publish_id": publish_id}).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {access_token}"},
        )
        data = self._json_request(request, 15)
        if data.get("error", {}).get("code") not in (None, "ok"):
            raise TikTokConfigurationError(data["error"].get("message", "TikTok publish status failed"))
        return data.get("data", data)

    @staticmethod
    def _json_request(request: urllib.request.Request, timeout: int) -> dict:
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as error:
            raw = error.read().decode("utf-8", "replace")
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = {}
            detail = payload.get("error", {}) if isinstance(payload, dict) else {}
            if isinstance(detail, dict):
                message = detail.get("message") or detail.get("description") or detail.get("code")
            else:
                message = str(detail) if detail else None
            message = message or (payload.get("message") if isinstance(payload, dict) else None) or raw[:300]
            raise TikTokConfigurationError(f"TikTok API HTTP {error.code}: {message or 'request rejected'}") from error
