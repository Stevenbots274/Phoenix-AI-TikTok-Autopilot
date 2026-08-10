"""AI Content Director and a safe local fallback for first-run development."""

from __future__ import annotations

import json
import os
import re
import time
import urllib.request
import uuid
from dataclasses import asdict, dataclass, field

from search_manager import SearchResult, serialise_results


FORMATS = ("VOICE_VIDEO", "MUSIC_VIDEO", "SLIDESHOW", "SILENT_VIDEO", "VOICE_MUSIC")


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
        if self.api_key:
            try:
                return self._remote_plan(context)
            except (OSError, ValueError, KeyError, TimeoutError, json.JSONDecodeError):
                pass
        return self._local_plan(context)

    def _remote_plan(self, context: dict) -> ContentPlan:
        system = (
            "You are Phoenix, a TikTok content director. Return only valid JSON with keys: "
            "topic,niche,format,voice_required,music_required,duration_seconds,hook,script,"
            "caption,hashtags,visual_instructions. format must be one of "
            f"{', '.join(FORMATS)}. Keep the script suitable for the requested duration."
        )
        user = json.dumps(context)
        payload = json.dumps(
            {
                "model": self.model,
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
        started = time.monotonic()
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        raw = data["choices"][0]["message"]["content"]
        parsed = json.loads(self._strip_code_fence(raw))
        plan = self._validate(parsed, context)
        plan.sources = context["sources"]
        plan.id = str(uuid.uuid4())
        return plan

    def _local_plan(self, context: dict) -> ContentPlan:
        topic = context["topic"]
        niche = context["niche"]
        requested = context["requested_format"]
        lower_topic = topic.lower()
        if topic == "Choose a fresh topic":
            topic = f"One practical {niche} idea creators can use this week"
        if requested and requested != "AUTO":
            selected = requested
        elif any(word in lower_topic for word in ("quote", "meme", "list", "visual")):
            selected = "MUSIC_VIDEO"
        elif any(word in lower_topic for word in ("breaking", "news", "announcement")):
            selected = "VOICE_MUSIC"
        else:
            selected = "VOICE_VIDEO"

        voice = selected in ("VOICE_VIDEO", "VOICE_MUSIC")
        music = selected in ("MUSIC_VIDEO", "VOICE_MUSIC")
        hook = f"Most people are missing this simple shift in {niche}."
        script = (
            f"Here is the useful part about {topic}. First, start with the smallest version you can test today. "
            "Second, look for one clear result instead of trying to automate everything at once. "
            "Third, keep what works and remove the friction. The advantage is not doing more busywork; "
            "it is creating a repeatable system that leaves you time to think. Follow for practical ideas "
            f"you can apply to {niche} without the hype."
        )
        hashtags = self._hashtags(niche)
        return ContentPlan(
            topic=topic,
            niche=niche,
            format=selected,
            voice_required=voice,
            music_required=music,
            duration_seconds=max(15, min(int(context["duration_seconds"]), 90)),
            hook=hook,
            script=script,
            caption=f"A practical take on {topic}. Save this for later.",
            hashtags=hashtags,
            visual_instructions=[
                "Open with bold kinetic text showing the hook",
                f"Use clean vertical visuals connected to {niche}",
                "End with a high-contrast follow call-to-action",
            ],
            sources=context["sources"],
        )

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

    @staticmethod
    def _hashtags(niche: str) -> list[str]:
        words = re.findall(r"[A-Za-z0-9]+", niche)
        tags = [f"#{word}" for word in words[:3]]
        return tags + ["#TikTokTips", "#LearnOnTikTok"]
