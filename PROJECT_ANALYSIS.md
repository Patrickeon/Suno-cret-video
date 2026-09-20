# Suno MV Studio - Project Analysis for Claude Code Setup

## Executive Summary

This repository is already a functioning media-creation product, not a prototype that needs a new architecture.

The current implementation naturally divides into four concerns:

1. Studio UX — Next.js UI, inputs, presets, sync UI, preview, render progress.
2. Application Backend — FastAPI, jobs, validation, settings, storage, provider orchestration.
3. Media Engine — FFmpeg, audio/timing, subtitles, backgrounds, effects, final encode.
4. Creative Direction — LLM palette/storyboard/edit behavior and the logic that decides what visual treatment fits a song.

For Claude Code, one giant “full-stack developer” persona would be too broad. The recommended setup is one concise root `CLAUDE.md` plus four project subagents in `.claude/agents/`. Claude Code officially supports project-level custom subagents there, and keeping the always-loaded root instructions short reduces instruction dilution.

## What Exists Today

### Media engine
`make_mv.py` is about 1,315 lines and already provides:
- duration probing;
- loudness normalization / mastering;
- `.lrc` parsing and `.txt` distribution;
- stable-ts automatic alignment;
- ASS subtitle generation;
- karaoke, subtitle fade, preview line;
- image backgrounds, Ken Burns, multiple-image crossfade;
- generated gradient backgrounds;
- AI/video background support via `--video-bg`;
- waves/bars/line/cqt/spectrum visualizers;
- disc/album-art mode;
- progress bar;
- scrim, vignette, film grain, sparkle, pulse;
- intro title and outro CTA;
- shorts and clip extraction;
- thumbnail/watermark/logo;
- 1080/1440/2160 and 24/30/60 fps output.

### Backend
`backend/main.py` exposes render, agent edit, storyboard, AI-video, palette, metadata, translation, batch, YouTube, job and cancellation APIs.

`backend/render.py` maps API options to the CLI, tracks render progress, and joins generated scenes/intro/outro media.

`backend/jobs.py` owns local job state/history persistence.

### Product-side AI
`backend/agent.py` already contains specialized prompts for:
- natural-language render-option editing;
- palette generation;
- storyboard generation;
- YouTube metadata;
- lyric translation.

`backend/video_providers.py` abstracts Replicate, fal.ai and mock video generation.

### Frontend
`frontend/app/page.tsx` is a large all-in-one studio page (~1,368 lines), but it already supports a substantial workflow:
- audio/lyrics/background/logo uploads;
- manual lyric sync;
- automatic alignment option;
- subtitle styling;
- visualizer/palette/preset controls;
- album/disc style;
- render quality/effects;
- preview and progress;
- history;
- batch song rendering;
- AI editing;
- storyboard / AI background generation;
- publishing helpers.

## Current Fit to the Desired YouTube Style

The repository already has both halves of the requested goal.

Playlist-like output already exists through stable composition, album art, Ken Burns, subtle visualizers, progress, lyrics and presets.

Music-video-like output already exists through AI video backgrounds and storyboard-generated clips.

The missing piece is not another renderer. The main gap is a higher-level creative plan that decides when to behave like a playlist and when to behave like a music video.

## Main Product Gaps

### 1. No explicit visual-mode abstraction
The current UI exposes many individual options, but there is no strong first-class concept such as:
- Playlist
- Hybrid / Mood Film
- Lyric MV
- Cinematic MV

Adding a high-level mode should configure existing options first, not duplicate render code.

### 2. Storyboard timing is not music-aware enough
The current storyboard flow generates N scenes and gives them effectively uniform coverage of the total duration.

For a stronger MV feeling, a future creative plan should attach scenes to meaningful timestamps such as:
- intro;
- verse;
- pre-chorus;
- chorus;
- bridge;
- climax;
- outro;
- meaningful lyric boundaries;
- energy/beat changes.

### 3. AI clip continuity needs to become a system, not just prompt text
The existing prompt already asks for consistent style, but stronger results require persistent creative attributes such as palette, environment, subject rules, camera language, lighting and negative constraints to be carried across every scene.

### 4. “Album batch” is not yet a single playlist compilation
The current frontend album action queues multiple independent song renders. That is useful, but it is different from producing one long YouTube playlist video with multiple tracks, a global timeline, track transitions, chapter/tracklist information and shared visual identity.

If the user wants true playlist compilation, it should become a separate feature rather than changing the existing batch behavior.

### 5. Two large files should be handled carefully
`make_mv.py` and `frontend/app/page.tsx` are large. This is a maintainability concern, but it is not a reason for a broad rewrite.

Claude should extract modules only when a concrete feature makes the extraction safer and easier to test.

## Validation Performed

Backend test suite:
- 92 tests passed.

Frontend:
- ESLint completed without source errors when invoked through its JS entrypoint.
- TypeScript `tsc --noEmit` completed successfully.
- The uploaded zip preserved `node_modules/.bin/eslint` without execute permission in this sandbox, which is a transfer/permission artifact rather than a TypeScript/ESLint source failure.

## Recommended Claude Code Strategy

Use:
- root `CLAUDE.md` for always-on project rules and architecture;
- `.claude/agents/studio-frontend.md` for UI/editor tasks;
- `.claude/agents/backend-engineer.md` for API/jobs/provider work;
- `.claude/agents/media-engineer.md` for FFmpeg/audio/sync/render work;
- `.claude/agents/creative-director.md` for Playlist/MV/Hybrid design and music-aware scene planning.

Do not force every task through a subagent. Simple fixes should remain in the main context. Use specialists for cross-domain or domain-heavy work.

## Recommended Next Product Step

The highest-leverage next feature is a backward-compatible `visual_mode` / creative preset layer rather than adding more isolated effects.

Suggested modes:
- `playlist`: stable background + subtle motion + lyrics/visualizer;
- `hybrid`: stable anchor + cinematic changes at musical sections;
- `lyric_mv`: lyrics remain central while backgrounds/scenes follow the song;
- `cinematic_mv`: scene plan is primary and subtitles can be reduced/optional.

Implementation should initially map these modes to existing options. Only after the UX is stable should the project introduce section-aware scene timing and a richer creative-plan schema.
