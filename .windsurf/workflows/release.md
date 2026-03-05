---
description: Publish iil-aifw to PyPI
---

# Release — PyPI Publish

## Build + Publish

```bash
bash ~/github/platform/scripts/publish-package.sh ~/github/aifw
```

## Test-Upload zuerst

```bash
bash ~/github/platform/scripts/publish-package.sh ~/github/aifw --test
```

## Verify

```bash
pip index versions iil-aifw 2>/dev/null | head -3
```

- Git tag `v<version>` wird automatisch erstellt
- `--dry-run` für sichere Tests
