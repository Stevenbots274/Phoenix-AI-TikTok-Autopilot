"""AI Content Director backed by the configured Phoenix AI Router."""

from __future__ import annotations

import json
import os
import re
import urllib.request
import uuid
from dataclasses import asdict, dataclass, field

from search_manager import SearchResult, serialise_results


FORMATS = ("VOICE_VIDEO", "MUSIC_VIDEO", "SLIDESHOW", "SILENT_VIDEO", "VOICE_MUSIC")


class ContentProviderError(RuntimeError):
    pass


@dataclass
class ContentPlan:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    topic: str = ""
    niche: str = "AI & technology"
    format: str = "VOICE_VIDEO"
    voice_required: bool = True
    music_required: bool = False
    duration_seconds: int = 35
    hook: str = ""
    script: str = ""
    caption: str = ""
    hashtags: list[str] = field(default_factory=list)
    visual_instructions: list[str] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class ContentDirector:
    def __init__(self, timeout: float = 25.0):
        self.endpoint = os.getenv(
            "PHOENIX_AI_ENDPOINT",
            "https://combined-alidia-suhailtechlnfo-01b0509f.koyeb.app",
        ).rstrip("/")
        self.api_key = os.getenv("PHOENIX_AI_API_KEY", "")
        self.model = os.getenv("PHOENIX_AI_MODEL", "GPT-5.6-SOL")
        self.fallback_model = os.getenv("PHOENIX_AI_FALLBACK_MODEL", "Claude Opus 5")
        self.timeout = timeout

    def generate(
        self,
        topic: str | None = None,
        niche: str = "AI & technology",
        requested_format: str | None = None,
        duration_seconds: int = 35,
        instructions: str = "",
        sources: list[SearchResult] | None = None,
    ) -> ContentPlan:
        context = {
            "topic": topic or "Choose a fresh topic",
            "niche": niche,
            "requested_format": requested_format or "AUTO",
            "duration_seconds": duration_seconds,
            "instructions": instructions,
            "sources": serialise_results(sources or []),
        }
        if not self.api_key:
            raise ContentProviderError("PHOENIX_AI_API_KEY is required for content generation")
        errors = []
        for model in (self.model, self.fallback_model):
            try:
                return self._remote_plan(context, model)
            except (OSError, ValueError, KeyError, TimeoutError, json.JSONDecodeError) as error:
                errors.append(error.__class__.__name__)
        raise ContentProviderError(
            f"Phoenix AI Router unavailable after primary and fallback models ({', '.join(errors)})"
        )

    def _remote_plan(self, context: dict, model: str) -> ContentPlan:
        system = (
            "You are Phoenix, a TikTok content director. Return only valid JSON with keys: "
            "topic,niche,format,voice_required,music_required,duration_seconds,hook,script,"
            "caption,hashtags,visual_instructions. format must be one of "
            f"{', '.join(FORMATS)}. Keep the script suitable for the requested duration."
        )
        user = json.dumps(context)
        payload = json.dumps(
            {
                "model": model,
                "temperature": 0.7,
                "max_tokens": 1400,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            }
        ).encode()
        request = urllib.request.Request(
            f"{self.endpoint}/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        raw = data["choices"][0]["message"]["content"]
        parsed = json.loads(self._strip_code_fence(raw))
        plan = self._validate(parsed, context)
        plan.sources = context["sources"]
        plan.id = str(uuid.uuid4())
        return plan

    def _validate(self, raw: dict, context: dict) -> ContentPlan:
        selected = str(raw.get("format", "VOICE_VIDEO")).upper()
        if selected not in FORMATS:
            selected = "VOICE_VIDEO"
        return ContentPlan(
            topic=str(raw.get("topic") or context["topic"]),
            niche=str(raw.get("niche") or context["niche"]),
            format=selected,
            voice_required=bool(raw.get("voice_required", selected in ("VOICE_VIDEO", "VOICE_MUSIC"))),
            music_required=bool(raw.get("music_required", selected in ("MUSIC_VIDEO", "VOICE_MUSIC"))),
            duration_seconds=max(15, min(int(raw.get("duration_seconds", context["duration_seconds"])), 90)),
            hook=str(raw.get("hook", "")),
            script=str(raw.get("script", "")),
            caption=str(raw.get("caption", "")),
            hashtags=[str(item) for item in raw.get("hashtags", [])][:12],
            visual_instructions=[str(item) for item in raw.get("visual_instructions", [])][:10],
        )

    @staticmethod
    def _strip_code_fence(value: str) -> str:
        return re.sub(r"^```(?:json)?\s*|\s*```$", "", value.strip(), flags=re.IGNORECASE)
