# Phoenix AI TikTok Autopilot

AI-powered automated TikTok content creation and publishing platform.

## Overview

Phoenix AI TikTok Autopilot is a web-based automation platform that allows users to create, schedule, and automatically publish TikTok content. It combines artificial intelligence, text-to-speech, media processing, scheduling, and TikTok publishing into one automated workflow.

## Key Features

- **AI Content Director** powered by Phoenix AI Router (Claude Opus 5 / GPT-5.6-SOL)
- **Adaptive Content Formats**: voice video, music video, slideshow, silent video, voice + music
- **Free-First TTS** with automatic fallback providers
- **FFmpeg Video Generation** with subtitle engine and templates
- **Official TikTok Publishing** via TikTok Content Posting API (OAuth)
- **Scheduling & Autopilot** with approval modes, retry system, and notifications

## Documentation

- [SRS Part 1](SRS.md) — Software Requirements Specification v1.0
- [SRS Part 2](SRS-part2.md) — SRS continuation (analytics, workflow, build order)

## Tech Stack

| Component | Technology |
|-----------|------------|
| Frontend / App | Next.js |
| Database | Supabase PostgreSQL |
| Storage | Supabase Storage |
| AI | Phoenix AI Router (Claude Opus 5, GPT-5.6-SOL) |
| Web Search | Tavily (primary), DuckDuckGo Instant Answer API and Serper.dev (backups) |
| Video | FFmpeg |
| Publishing | TikTok Content Posting API |
