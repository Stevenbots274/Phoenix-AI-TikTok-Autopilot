# Phoenix AI TikTok Autopilot

AI-powered automated TikTok content creation and publishing platform. This repository now includes a runnable, dependency-free MVP built around the blueprint.

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

- [Blueprint v1.0](blueprint%20v1.0.md) — Software Requirements Specification (full master blueprint, chapters 1–5.18 plus end-to-end workflow and build order)

## Run Locally

The MVP uses Python's standard library and SQLite, so no package installation is required.

```bash
python3 server.py
```

Open `http://127.0.0.1:8000`. Copy `.env.example` to `.env` only when enabling provider integrations. The local content director works without an API key and produces structured plans for all supported formats.

## Included MVP

- Dashboard with automation status, queue counts, recent content, and system health
- Content Studio for AI-directed structured content plans
- Local deterministic fallback when the Phoenix AI Router is not configured
- Phoenix AI Router adapter with model fallback-ready configuration
- Tavily, DuckDuckGo, and Serper search adapter chain
- SQLite schema for profiles, settings, content, scripts, videos, schedules, notifications, usage, and logs
- Approval and automatic automation modes with scheduling records
- FFmpeg/TTS media boundary with 1080x1920 MP4 validation and clear setup status
- TikTok OAuth and Content Posting API boundary with backend-only token storage

## TikTok Setup

TikTok credentials are not required to run the dashboard or generate content. Before connecting or publishing, create an approved TikTok developer app and set `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`, and `TIKTOK_REDIRECT_URI` from `.env.example`. The app must have the appropriate approved scopes, including `user.info.basic` and `video.publish` where TikTok grants them.

The publishing boundary expects a publicly reachable rendered video URL. Actual rendering and the worker that uploads generated media are intentionally isolated behind `media_engine.py` for the next implementation milestone.

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
