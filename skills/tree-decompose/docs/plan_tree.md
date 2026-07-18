# Plan Tree Template

This file is produced by the **Architect** subagent during Phase 2.
It contains a human-readable outline of the recursive decomposition.

## Example: Viral App Factory

- node_000: `src/types/index.ts` — global types and enums (contract)
  - node_001: `src/services/auth/session.ts` — validate Discord OAuth sessions
    - node_002: `src/lib/oauth/discord.ts` — Discord OAuth client utility
  - node_003: `src/services/project/create.ts` — create project from template
    - node_004: `src/lib/templates/registry.ts` — template registry and defaults
  - node_005: `src/services/deployment/deploy.ts` — trigger deployment hook
    - node_006: `src/lib/hooks/vercel.ts` — Vercel deployment adapter
  - node_007: `src/services/billing/subscription.ts` — Stripe subscription manager
    - node_008: `src/lib/stripe/client.ts` — Stripe API client wrapper
  - node_009: `src/app/page.tsx` — main dashboard UI
    - node_010: `src/components/project-card.tsx` — reusable project card component

Each leaf maps 1:1 to a row in `state/ledger.json`.
