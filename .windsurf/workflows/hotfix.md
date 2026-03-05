---
description: Schneller Fix
---

# Hotfix

// turbo
```bash
git log --oneline -10
git checkout -b hotfix/$(date +%Y%m%d)-BESCHREIBUNG
```

Fix → Test → `pytest tests/ -q` → PR → Release
