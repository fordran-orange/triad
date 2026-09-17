# Rotation engine

The configurable default sequence is CODEX -> CLAUDE -> GROK -> CODEX. Each stage selects an eligible backlog candidate, reserves the member's daily opportunity, creates and validates a WorkItem, captures source evidence, requests a proposal and evaluates it. Only low-risk, reversible, scoped documentation/research text work can proceed under current policy.

Implementation returns structured content. The broker checks a clean main base, creates `codex/triad/<agent>/<work-id>` in an isolated worktree, validates paths and size, applies files, runs deterministic host checks and creates the change commit. Journal and canonical handoff precede independent review. The next member receives source context/diff/checks and returns APPROVE, REJECT or REQUEST_CHANGES. Host checks repeat; a separate review commit records the review. Merge requires the exact reviewed change/review commits, unchanged base, different reviewer, active controls, approved proposal and no unresolved disagreement. Git hooks are disabled for broker operations.

A rejection, disagreement or pending human merge stops progression. NO_CHANGE_JUSTIFIED is valid and records its explanation without a synthetic Git change. Each primary member receives at most one opportunity per day; failed attempts consume their reservation. CycleSummary records accepted/rejected/reverted changes, reviews, tests, usage, failures and next candidates, with an Obsidian Markdown projection.

Git and PostgreSQL cannot commit atomically together. GitCheckpoint records retain branch/base/change commits; interrupted work is blocked for reconciliation. The protected baseline is enforced by the local broker; repository-host branch protection and a durable job queue are not installed.
