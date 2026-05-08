# P3 Design Note — UnifiedConfig and Startup Validation

**Created**: 2026-05-07
**Supplements**: `docs/superpowers/plans/2026-04-26-config-consolidation.md`
**Status**: approved — written to unblock P3 implementation

---

## Gap addressed

The existing plan covers file migration. This note covers the missing pieces:
`UnifiedConfig`, `ConfigValidationError`, startup validation hook, and CLI surface.

---

## UnifiedConfig

Location: `mahavishnu/core/unified_config.py`

```python
class ConfigValidationError(Exception):
    errors: list[str]
    file_path: str | None

class UnifiedConfig:
    def validate(self, settings_dir: Path = Path("settings")) -> ConfigValidationReport
    @classmethod
    def validate_strict(cls, settings_dir: Path = Path("settings")) -> None  # raises ConfigValidationError
```

`UnifiedConfig.validate()` calls the existing `validate_config()` from `config_validator.py` and extends it with Pydantic-level validation of `MahavishnuSettings` (catches `ValidationError`). It covers all five files:

| File | Validated by |
|------|-------------|
| `mahavishnu.yaml` | Pydantic (`MahavishnuSettings`) + YAML syntax |
| `local.yaml` | YAML syntax only (optional, overrides only) |
| `models.yaml` | YAML syntax + key presence check |
| `embeddings.yaml` | YAML syntax + key presence check |
| `repos.yaml` / `ecosystem.yaml` | Existing `ConfigValidator.validate_repos_yaml()` |

---

## ConfigValidationError

Raised by `validate_strict()` when any error is found. Carries:
- `errors: list[str]` — human-readable error messages
- `file_path: str | None` — the file that caused the first error (best-effort)

---

## Startup validation hook

`MahavishnuApp.wait_for_dependencies()` already exists and runs at startup. After the dependency health check, call:

```python
if self.config.unified_validation_enabled:
    UnifiedConfig.validate_strict()
```

Default: `unified_validation_enabled = False` (soft-launch). Enable via `--config-strict` CLI flag or env var `MAHAVISHNU_UNIFIED_VALIDATION_ENABLED=true`.

---

## CLI surface

`mahavishnu config validate` → calls `UnifiedConfig.validate()`, prints report.

The `config` sub-group already exists in the CLI. Add `validate` as a new command in the appropriate CLI module (check `cli/` directory).

---

## Soft-launch strategy

- Default: validation runs in report-only mode (warnings logged, no startup block)
- `--config-strict` or env var: strict mode — bad config raises `ConfigValidationError` and aborts startup
- This preserves backward compatibility while giving operators an opt-in path to strict validation
