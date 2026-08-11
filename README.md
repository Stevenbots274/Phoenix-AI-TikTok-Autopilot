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

The app uses Python and Supabase PostgreSQL. Render installs the single database driver from `requirements.txt` during deployment.

```bash
python3 server.py
```

Open `http://127.0.0.1:8000`. Copy `.env.example` to `.env` only when enabling provider integrations. The local content director works without an API key and produces structured plans for all supported formats.

## Public Pages and Authentication

- `/` is the public landing page
- `/signup` creates an account immediately; email verification is intentionally not required
- `/login` signs in to the protected workspace
- `/app` is the authenticated dashboard
- `/about`, `/help`, `/contact`, `/security`, and `/cookies` are public company, support, trust, and policy pages
- `/terms` and `/privacy` are public legal pages for the TikTok developer app

Passwords are stored as salted scrypt hashes. Sessions use HttpOnly cookies, and content records are scoped to the signed-in account.

## Included MVP

- Dashboard with automation status, queue counts, recent content, and system health
- Content Studio for AI-directed structured content plans
- Phoenix AI Router adapter with primary and fallback model configuration
- Tavily, DuckDuckGo, and Serper search adapter chain
- Supabase PostgreSQL schema for profiles, settings, content, scripts, videos, schedules, notifications, usage, and logs
- Approval and automatic automation modes with scheduling records
- FFmpeg/TTS media boundary with 1080x1920 MP4 validation and clear setup status
- TikTok OAuth and Content Posting API boundary with backend-only token storage and a creator-settings check before posting

## TikTok Setup

TikTok credentials are not required to run the dashboard or generate content. Before connecting or publishing, create an approved TikTok developer app and set `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`, and `TIKTOK_REDIRECT_URI` from `.env.example`. The app must have the appropriate approved scopes, including `user.info.basic` and `video.publish` where TikTok grants them.

For the deployed domain, use these URLs in the TikTok developer console:

- Terms of Service: `https://tiktok.senseiphoenix.name.ng/terms`
- Privacy Policy: `https://tiktok.senseiphoenix.name.ng/privacy`
- OAuth redirect URI: `https://tiktok.senseiphoenix.name.ng/api/tiktok/oauth/callback`

The publishing boundary expects a publicly reachable rendered video URL. Actual rendering and the worker that uploads generated media are intentionally isolated behind `media_engine.py` for the next implementation milestone.

## Tech Stack

| Component | Technology |
|-----------|------------|
| Frontend / App | HTML, CSS, JavaScript, Python |
| Database | Supabase PostgreSQL |
| Storage | Local/Render storage boundary |
| AI | Phoenix AI Router (Claude Opus 5, GPT-5.6-SOL) |
| Web Search | Tavily (primary), DuckDuckGo Instant Answer API and Serper.dev (backups) |
| Video | FFmpeg |
| Publishing | TikTok Content Posting API |
