---
description: Pflicht-Ritual vor jeder Coding-Agent-Session
---

# Agent Session Start

## Kontext laden
```
1. docs/CORE_CONTEXT.md
2. docs/AGENT_HANDOVER.md
3. docs/adr/README.md
```

## Syncen + Status
// turbo
```bash
bash ~/github/platform/scripts/sync-repo.sh
git status && git log --oneline -5
```

## Plan
Komplexität: trivial|simple|moderate|complex — bei moderate+ → `/agentic-coding`

## Session-Ende
- [ ] AGENT_HANDOVER.md aktualisiert
- [ ] Tests grün
- [ ] `bash ~/github/platform/scripts/sync-repo.sh`
