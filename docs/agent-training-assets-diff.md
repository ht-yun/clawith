# Agent Training Assets Difference Document

## Comparison Baseline

This document compares:

- Original version: commit immediately before `649007e`
- Current feature version: commit `649007e` on branch `feature/agent-training-assets`

In other words, the baseline is the repository state before the "agent training assets and distillation UI" feature was added.


## Change Goal

The original version did not have an agent-scoped training asset system.

The new version adds:

- agent-level memory portrait storage
- agent-level golden clarifying question storage
- chat-session-based distillation into draft training assets
- runtime injection of those assets into agent context
- a front-end management panel inside the Agent Detail `mind` tab


## Main Functional Differences

### 1. New persistent training asset models

The original version had no dedicated data model for reusable training assets.

The new version adds two database-backed models:

- `AgentMemoryPortrait`
- `AgentGoldenQuestion`

These models allow training data to be stored independently from workspace files such as `memory/knowledge.md` or `focus.md`.


### 2. New backend API surface

The original version had no API for CRUD or distillation of training assets.

The new version adds new endpoints under:

- `/api/agents/{agent_id}/training/memory-portrait`
- `/api/agents/{agent_id}/training/golden-questions`

Supported capabilities:

- list items
- create items
- update items
- delete items
- distill draft candidates from an existing chat session


### 3. New distillation workflow

The original version had no mechanism to convert historical chat sessions into reusable training data.

The new version adds an LLM-backed distillation flow that:

- loads chat messages from a selected session
- extracts durable preference/alignment signals into memory portrait candidates
- extracts reusable clarification patterns into golden question candidates
- returns draft candidates without auto-saving them


### 4. Runtime agent context now includes training assets

The original version built runtime context from existing memory/focus/workspace sources only.

The new version additionally injects:

- `Training Memory Portrait`
- `Golden Clarifying Questions`

These sections are appended dynamically during agent context assembly when active training assets exist.


### 5. New front-end management UI

The original version did not expose any training-asset UI in the agent detail page.

The new version adds a new panel in the `mind` tab that supports:

- viewing existing memory portraits
- viewing existing golden questions
- creating and editing items
- deleting items
- selecting historical chat sessions for distillation
- adopting selected draft candidates into persistent records


## Files Changed

### New files

- `backend/app/api/agent_training.py`
- `backend/app/models/training_asset.py`
- `frontend/src/components/AgentTrainingAssetsPanel.tsx`

### Updated files

- `backend/app/main.py`
- `backend/app/scripts/bootstrap_db.py`
- `backend/app/services/agent_context.py`
- `backend/seed.py`
- `frontend/src/pages/AgentDetail.tsx`
- `frontend/src/services/api.ts`


## Folder-Level Impact

The modified folders introduced or touched by this feature are:

- `backend/app/api/`
- `backend/app/models/`
- `backend/app/scripts/`
- `backend/app/services/`
- `backend/`
- `frontend/src/components/`
- `frontend/src/pages/`
- `frontend/src/services/`
- `docs/`


## Before vs After Summary

### Before

- no reusable training asset data model
- no training asset API
- no distillation pipeline from chat history
- no runtime injection for portrait/question assets
- no UI to manage such assets

### After

- training assets can be stored per agent
- chat sessions can be distilled into draft assets
- selected assets can be promoted into persistent records
- agent runtime context can consume active portrait/question assets
- users can manage the full flow from the Agent Detail page


## Files/Folders to Deliver Together

If this feature is packaged or reviewed as a unit, the following paths should be treated as part of the same change set:

- `backend/app/api/agent_training.py`
- `backend/app/models/training_asset.py`
- `backend/app/main.py`
- `backend/app/scripts/bootstrap_db.py`
- `backend/app/services/agent_context.py`
- `backend/seed.py`
- `frontend/src/components/AgentTrainingAssetsPanel.tsx`
- `frontend/src/pages/AgentDetail.tsx`
- `frontend/src/services/api.ts`
- `docs/agent-training-assets-diff.md`


## Notes

- This document describes only the training-assets feature introduced by commit `649007e`.
- Other uncommitted local workspace changes are intentionally excluded from this comparison.
