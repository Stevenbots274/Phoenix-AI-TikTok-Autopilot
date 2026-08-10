Yes. Let's restart it cleanly and make this the master SRS for the project. I’ll build the specification around your actual setup: your hosted Phoenix AI Router, Claude Opus 5 / GPT-5.6-SOL, adaptive voice/music content, free-first TTS with fallback providers, FFmpeg video generation, scheduling, and official TikTok publishing.

Phoenix AI TikTok Autopilot

Software Requirements Specification — SRS v1.0

Project Type: AI-powered automated TikTok content creation and publishing platform
Primary AI: Phoenix AI Router
AI Endpoint: combined-alidia-suhailtechlnfo-01b0509f.koyeb.app
Available Models: Claude Opus 5, GPT-5.6-SOL
Primary Platform: TikTok
Publishing Method: TikTok official Content Posting API
Video Engine: FFmpeg
Database: Supabase PostgreSQL
Storage: Supabase Storage
Architecture: Web application + backend worker + scheduled job system


---

CHAPTER 1 — PLATFORM FOUNDATION, AUTHENTICATION & CONFIGURATION

1.1 System Overview

Phoenix AI TikTok Autopilot is a web-based automation platform that allows users to create, schedule, and automatically publish TikTok content.

The platform combines artificial intelligence, text-to-speech, media processing, scheduling, and TikTok publishing into one automated workflow.

The core objective is:

> Allow a user to configure their content once and let Phoenix automatically create and publish suitable TikTok posts every day.



The system must not require every post to follow the same format.

Depending on the topic, the AI may create:

🎙️ Voice video

🎵 Music-only video

🖼️ Image/slideshow post

🎬 Silent video

🎙️ + 🎵 Voice with background music



---

1.2 Core System Architecture

PHOENIX AUTOPILOT
                                │
             ┌──────────────────┼──────────────────┐
             │                  │                  │
             ▼                  ▼                  ▼
        USER SYSTEM        AI CONTENT          AUTOMATION
             │               ENGINE                │
             │                  │                  │
             │                  ▼                  │
             │           PHOENIX AI ROUTER         │
             │                  │                  │
             │        ┌─────────┴─────────┐        │
             │        ▼                   ▼        │
             │   Claude Opus 5       GPT-5.6-SOL  │
             │        │                   │        │
             │        └─────────┬─────────┘        │
             │                  ▼                  │
             │            Content Plan             │
             │                  │                  │
             │        ┌─────────┴─────────┐        │
             │        ▼         ▼         ▼        │
             │      Voice     Music     Visuals    │
             │        │         │         │        │
             │        └─────────┼─────────┘        │
             │                  ▼                  │
             │              FFmpeg                 │
             │                  │                  │
             │                  ▼                  │
             │             Final Content           │
             │                  │                  │
             └──────────────────┼──────────────────┘
                                ▼
                           SCHEDULER
                                │
                                ▼
                         TIKTOK API
                                │
                                ▼
                           PUBLISHED


---

1.3 User Authentication

The system shall provide secure user authentication.

Required functionality

Registration

Login

Logout

Email verification

Password reset

Password change

Account deletion

Session management


Optional authentication

Google

GitHub



---

1.4 User Dashboard

The dashboard shall provide a complete overview of the automation system.

Dashboard widgets

TikTok Account
Automation Status
Today's Content
Next Scheduled Post
Generated Videos
Published Videos
Failed Posts
AI Usage
TTS Usage

Example:

PHOENIX AUTOPILOT

🟢 AUTOMATION ACTIVE

TikTok
@youraccount

Today's Post
"3 Web3 Things You Need To Know"

Format
🎵 Music Video

Scheduled
8:00 PM

Next generation
Tomorrow — 7:00 AM


---

1.5 User Profile

Users shall be able to configure:

Display name

Username

Profile picture

Timezone

Default language

Default content niche

Default posting schedule

AI personality

Content preferences



---

1.6 TikTok Account Management

Users shall be able to connect one or more TikTok accounts where supported by the application's approved API permissions.

Interface:

TikTok Accounts

┌──────────────────────────┐
│ 🟢 @PhoenixWeb3          │
│ Connected                │
│                          │
│ [Manage] [Disconnect]    │
└──────────────────────────┘

[ + Connect TikTok ]


---

1.7 TikTok OAuth

TikTok authentication shall use the official OAuth flow.

Process:

Connect TikTok
       ↓
TikTok Login
       ↓
User authorization
       ↓
Authorization code
       ↓
Backend exchanges code
       ↓
Access token
       ↓
Refresh token
       ↓
Account connected

Tokens shall be handled exclusively by the backend.


---

1.8 Security

Sensitive information must never be exposed to the browser.

Protected information includes:

AI API keys

TikTok client secrets

TikTok access tokens

Refresh tokens

TTS credentials

Supabase service-role credentials

Internal API credentials


The application shall use:

HTTPS

Secure sessions

OAuth state validation

Rate limiting

Authorization middleware

Row Level Security

Encrypted secrets

Audit logs



---

CHAPTER 2 — AI CONTENT DIRECTOR & ADAPTIVE AUDIO ENGINE

This chapter contains the intelligence behind the platform.

2.1 Phoenix AI Router

The system shall use the user's hosted AI endpoint as the central text-generation service.

Base endpoint:

https://combined-alidia-suhailtechlnfo-01b0509f.koyeb.app

The application should communicate with the AI through a standardized backend adapter rather than hard-coding individual models throughout the application.


---

2.2 Supported AI Models

Initial models:

Claude Opus 5
GPT-5.6-SOL

The AI provider architecture should allow additional models to be added later.

Example:

AI Provider
    │
    ├── GPT-5.6-SOL
    ├── Claude Opus 5
    └── Future Models


---

2.3 AI Provider Configuration

Admin configuration:

Provider
Endpoint
Model
API key
Temperature
Maximum tokens
Timeout
Retry count

The system should support selecting:

Primary model

The default model used for content generation.

Fallback model

Used when the primary model fails or becomes unavailable.

Example:

Primary:
GPT-5.6-SOL

Fallback:
Claude Opus 5


---

2.4 Content Niche

Users shall configure one or more niches.

Examples:

Web3

Crypto

AI

Technology

Finance

Motivation

Education

Gaming

Business

Entertainment

Football

Personal brand


Custom niches must also be supported.


---

2.5 Content Instructions

Users can provide permanent instructions.

Example:

> Create short, engaging Web3 content for TikTok. Keep the tone confident, educational and easy to understand. Avoid unnecessary filler. Use strong hooks and clear CTAs.



These instructions are included in the AI content-generation context.


---

2.6 AI Topic Research

The AI shall determine suitable topics for each scheduled post.

Possible information sources:

Current web information

RSS feeds

User-provided topics

Trending subjects

News

Previous content

Content performance


Topics shall be evaluated using:

Freshness
Relevance
Engagement potential
Niche compatibility
Duplicate risk
Content quality
Safety


---

2.7 AI Content Director

The AI shall not simply generate a script.

It acts as a content director.

It decides:

What topic to cover

What hook to use

Which content format is appropriate

Whether voice is required

Whether music is required

What visuals are needed

Video length

Caption

Hashtags

CTA



---

2.8 Adaptive Content Formats

The system shall support:

FORMAT 1 — VOICE VIDEO

Script
+
AI Voice
+
Visuals
+
Subtitles
+
Optional Music

FORMAT 2 — MUSIC VIDEO

Text
+
Visuals
+
Animated captions
+
Music

FORMAT 3 — SLIDESHOW

Images
+
Text
+
Transitions
+
Music

FORMAT 4 — SILENT VIDEO

Video/Images
+
Animated Text
+
No Audio

FORMAT 5 — VOICE + MUSIC

AI Voice
+
Background Music
+
Visuals
+
Subtitles


---

2.9 AI Format Selection

Voice must not be mandatory.

The AI should determine whether narration improves the content.

Example:

Topic: "How a new airdrop works"

→ VOICE_VIDEO

Topic: "Motivational quote"

→ MUSIC_VIDEO

Topic: "5 crypto memes"

→ MUSIC_VIDEO

Topic: "Breaking Web3 announcement"

→ VOICE + MUSIC

The final AI response should use structured JSON so the backend knows exactly what to build.

Example:

{
  "format": "VOICE_VIDEO",
  "voice_required": true,
  "music_required": true,
  "duration_seconds": 35,
  "topic": "Example topic",
  "hook": "Example hook",
  "script": "Example script",
  "caption": "Example caption",
  "hashtags": [
    "#Web3",
    "#Crypto"
  ],
  "visual_instructions": [
    "Show blockchain visuals",
    "Show relevant project logo"
  ]
}


---

2.10 Script Generation

The AI shall generate:

Hook

Introduction

Main content

CTA

Caption

Hashtags

Visual instructions


The script length must match the requested duration.


---

2.11 Voice AI / TTS

TTS shall only be called when:

voice_required = true

This is important for reducing API usage.

The TTS system shall support multiple providers.

TTS Manager
    │
    ├── Provider A
    ├── Provider B
    ├── Provider C
    └── Self-hosted TTS


---

2.12 Free-First TTS Strategy

The system should prioritize free providers.

Example:

Primary Free TTS
       ↓
Quota exceeded?
       ↓
Fallback Free TTS
       ↓
Quota exceeded?
       ↓
Another provider
       ↓
Self-hosted TTS

The application shall never assume that a provider's quota resets daily.

Provider-specific reset information should be configurable.


---

2.13 TTS Quota Manager

Track:

Characters used
Characters remaining
Requests
Audio duration
Provider
Reset date
Status

Example:

TTS PROVIDERS

Provider A
8,500 / 10,000
🟢 Available

Provider B
10,000 / 10,000
🟡 Quota exhausted

Provider C
Available
🟢


---

2.14 Voice Settings

Users can configure:

Voice

Language

Speed

Pitch where supported

Provider

Voice style where supported



---

2.15 Music System

Music shall be optional.

The system should support:

Music ON
Music OFF

If music is required, the video engine should select from a configured library of legally usable audio assets.

The platform should not automatically scrape copyrighted TikTok music and redistribute it.


---

CHAPTER 3 — MEDIA ENGINE & CONTENT STUDIO

3.1 Video Generation Pipeline

The video engine transforms AI output into final TikTok content.

AI Content Plan
      ↓
Visual Collection
      ↓
Voice (if required)
      ↓
Music (if required)
      ↓
Subtitles (if required)
      ↓
Text Animation
      ↓
Branding
      ↓
FFmpeg
      ↓
Final MP4


---

3.2 Visual Sources

The platform shall support:

User-uploaded images

User-uploaded videos

Free stock media

Generated images

Existing media library


AI shall provide visual instructions.

Example:

Visual 1:
Bitcoin chart

Visual 2:
Blockchain animation

Visual 3:
Crypto wallet


---

3.3 Video Specifications

Default output:

Resolution: 1080 × 1920
Aspect Ratio: 9:16
Container: MP4
Video: H.264
Audio: AAC

The system shall validate the output before sending it to TikTok.


---

3.4 Subtitle Engine

For voice videos, subtitles shall be generated automatically.

Features:

Automatic timing

Word highlighting

Text animation

Font selection

Position

Size

Background

Line breaks



---

3.5 Text-Only Videos

For music-only and silent videos, text animation can replace voice narration.

Example:

WEB3 IS MOVING FAST 👀

3 things you need to know...

#1
...

#2
...

#3
...

FOLLOW FOR MORE


---

3.6 Visual Templates

The system shall provide reusable templates.

Examples:

News
Educational
List
Quote
Storytelling
Breaking News
Meme
Tutorial
Product/Project

Each template defines:

Layout

Font

Text placement

Animation

Transition

Audio behavior



---

3.7 Branding

Branding shall be configurable.

Users can optionally configure:

Logo

Username

Intro

Outro

CTA

Typography


However, branding must be implemented in a way that complies with the publishing platform's current content-sharing requirements.


---

3.8 Content Studio

The Content Studio shall allow users to inspect generated content before publishing.

Actions:

▶ Preview

✏️ Edit Script

🎙️ Change Voice

🎵 Change Music

🖼️ Change Visuals

🔄 Regenerate

📝 Edit Caption

📅 Schedule

🚀 Publish


---

3.9 Content Status

Each content item shall have one of the following statuses:

DRAFT
RESEARCHING
GENERATING
VOICE_GENERATING
VIDEO_RENDERING
READY
WAITING_APPROVAL
SCHEDULED
PUBLISHING
PUBLISHED
FAILED
CANCELLED


---

3.10 Content Library

All generated content shall be stored in the library.

Each item shall show:

Thumbnail

Title

Format

Status

Creation date

Scheduled date

Publishing status



---

CHAPTER 4 — AUTOMATION, SCHEDULING & TIKTOK PUBLISHING

4.1 Automation Engine

The automation engine runs content generation and publishing without requiring the user to keep the dashboard open.

Example:

07:00
Research

07:05
Script

07:10
Voice if required

07:15
Visuals

07:20
Render

07:25
Quality check

20:00
Publish


---

4.2 Automation Modes

Automatic Mode

Research
↓
Generate
↓
Render
↓
Schedule
↓
Publish

No approval required.

Approval Mode

Research
↓
Generate
↓
Render
↓
Notify user
↓
User approves
↓
Schedule
↓
Publish


---

4.3 Scheduling

Users shall configure:

Posts per day

Posting time

Posting days

Timezone

Content type

Automation mode


Example:

Posts/day:
1

Time:
8:00 PM

Timezone:
Africa/Lagos

Days:
Every day

Mode:
Automatic


---

4.4 Multiple Daily Posts

The platform shall support multiple posts per day.

Example:

08:00 AM
🎵 Music Video

02:00 PM
🎙️ Voice Video

08:00 PM
🎵 Music Video

The AI can automatically vary the content format to avoid repetitive content.


---

4.5 Content Queue

The system shall maintain a queue.

QUEUE

1. 🟢 Ready
2. 🟡 Scheduled
3. 🟡 Scheduled
4. 🟡 Generating
5. ⚪ Draft

If one generation fails, other scheduled content should not be affected.


---

4.6 TikTok Publishing Engine

Publishing shall use the official TikTok Content Posting API.

Process:

Scheduled post
      ↓
Validate TikTok account
      ↓
Validate token
      ↓
Validate media
      ↓
Initialize post
      ↓
Submit content
      ↓
Track status
      ↓
Save result


---

4.7 TikTok Token Management

The backend shall monitor token status.

If possible:

Expired
 ↓
Refresh
 ↓
New token
 ↓
Continue

If refresh fails:

Pause publishing
 ↓
Notify user
 ↓
Request reconnect


---

4.8 Publishing Failure Recovery

The system shall automatically retry temporary failures.

Example:

FAILED
 ↓
Retry 1
 ↓
Retry 2
 ↓
Retry 3
 ↓
SUCCESS

Permanent failures should be marked as failed and displayed to the user.


---

4.9 Duplicate Protection

The system must prevent accidentally publishing the same content multiple times.

Before retrying, the backend checks:

Post ID
Content ID
Publishing status
TikTok response


---

4.10 Publishing Calendar

The calendar shall display:

🟡 Scheduled
🔵 Generating
🟢 Published
🔴 Failed
⚪ Draft

Users can click any scheduled content to:

Preview

Edit

Reschedule

Cancel

Publish immediately



---

4.11 Notifications

Notifications shall be available through:

Dashboard

Email

Optional Telegram notification

Optional browser push


Events:

Video ready
Approval required
Video published
Publishing failed
TikTok disconnected
TTS quota exhausted
AI unavailable


---

CHAPTER 5 — DATABASE, ADMINISTRATION, MONITORING & SCALABILITY

5.1 Database

The recommended database is:

Supabase PostgreSQL

Core tables:

users
profiles

tiktok_accounts

ai_providers
ai_models

content_settings
content_topics
content_plans
scripts

tts_providers
tts_voices
tts_usage

media_assets
music_assets
videos

scheduled_posts
published_posts

automation_settings

notifications

api_usage
system_logs


---

5.2 Users Table

users
├── id
├── email
├── password_hash/auth_provider
├── status
├── created_at
└── updated_at


---

5.3 TikTok Accounts Table

tiktok_accounts
├── id
├── user_id
├── open_id
├── username
├── access_token
├── refresh_token
├── expires_at
├── refresh_expires_at
├── scopes
├── status
└── created_at

Sensitive token fields must be securely protected.


---

5.4 Content Table

A content record should contain:

content_id
user_id
topic
format
duration
hook
script
caption
hashtags
voice_required
music_required
visual_instructions
status
created_at


---

5.5 Video Table

videos
├── id
├── content_id
├── storage_url
├── thumbnail_url
├── duration
├── resolution
├── file_size
├── render_status
├── created_at
└── expires_at


---

5.6 Scheduled Posts

scheduled_posts
├── id
├── content_id
├── tiktok_account_id
├── scheduled_at
├── timezone
├── status
├── retry_count
└── created_at


---

5.7 Published Posts

published_posts
├── id
├── scheduled_post_id
├── tiktok_post_id
├── published_at
├── status
├── response_data
└── error_message


---

5.8 AI Usage Monitoring

Track:

Model
Requests
Input tokens
Output tokens
Execution time
Errors
Date

This helps identify which model is most efficient.


---

5.9 TTS Usage Monitoring

Track:

Provider
Characters
Requests
Audio duration
Quota
Reset date
Status

This enables automatic fallback.


---

5.10 Admin Dashboard

The administrator shall have access to:

Overview
Users
TikTok Accounts
AI Providers
TTS Providers
Videos
Scheduled Posts
Published Posts
Failed Jobs
Usage
Logs
System Settings


---

5.11 System Health

Admin dashboard:

SYSTEM HEALTH

Database       🟢
AI Router      🟢
Scheduler      🟢
Video Engine   🟢
Storage        🟢
TikTok API     🟢
TTS Provider A 🟢
TTS Provider B 🟡


---

5.12 Job Queue

Long-running operations should not run directly inside ordinary HTTP requests.

Use a background worker for:

AI generation
TTS generation
Video rendering
Media processing
Scheduled publishing
Analytics synchronization
Cleanup

Recommended architecture:

Web App
   ↓
Job Queue
   ↓
Worker
   ├── AI Worker
   ├── TTS Worker
   ├── Video Worker
   └── TikTok Worker


---

5.13 Retry System

Each background job should have:

Maximum retries
Retry delay
Error type
Job status
Last attempt
Next attempt

Transient errors should automatically retry.

Permanent errors should stop retrying.


---

5.14 Storage Management

Generated media should be stored in Supabase Storage.

Example:

/videos/
   2026/
      08/
         video_001.mp4
         video_002.mp4

The system should support automatic cleanup of old files to reduce storage usage.


---

5.15 Cost Optimization

The platform shall follow a free-first architecture.

Priority:

1. Existing hosted AI
2. Free TTS
3. TTS fallback
4. Free/owned visual assets
5. FFmpeg
6. Free infrastructure tiers where practical

The platform should only call expensive services when explicitly enabled.


---

5.16 Future Multi-Platform Architecture

The publishing layer should be modular.

Publisher
│
├── TikTok
├── YouTube Shorts
├── Instagram Reels
├── Facebook Reels
├── X
└── Future platforms

This allows Phoenix Autopilot to become a multi-platform content automation platform later.


---

5.17 Future AI Video Generation

The first version does not require an AI video-generation API.

Later:

Video Provider Manager
│
├── FFmpeg
├── AI Image Generator
├── AI Video Generator
└── User Media

The AI content director can decide which method is appropriate.


---

5.18 Future Analytics Intelligence

Eventually, the system can analyze performance:

Views
Likes
Comments
Shares
Engagement
Watch time where available

Then AI can learn:

Bes