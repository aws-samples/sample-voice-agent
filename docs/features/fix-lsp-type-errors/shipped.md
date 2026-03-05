---
id: fix-lsp-type-errors
name: Fix LSP Type Errors
type: tech-debt
priority: P1
effort: Medium
impact: High
status: shipped
created: 2026-03-05
started: 2026-03-05
shipped: 2026-03-05
---

# Shipped: Fix LSP Type Errors

## Summary

Eliminated all 25 pyright type errors across 10 files in the voice agent codebase and resolved 54 import errors by creating a `pyrightconfig.json`. Fixes include proper Union types for transcription frames, TypedDict corrections for flow results, Optional narrowing with None guards, and targeted `type: ignore` annotations for SDK union types that cannot be resolved statically.

## What Was Built

### Phase 0: Pyright Configuration
- Created `pyrightconfig.json` to establish proper project-level type checking
- Resolved all 54 import errors and 7 additional artifacts from the configuration

### Phase 1: Type Error Fixes (25 errors across 10 files)

| File | Errors Fixed | Approach |
|------|-------------|----------|
| `transitions.py` | 5 | FlowResult TypedDict -> `dict[str, Any]` |
| `flow_config.py` | 1 | Fix return type for `_build_global_functions()` |
| `observability.py` | 5 | Widen `_handle_transcription` to `Union[TranscriptionFrame, InterimTranscriptionFrame]`, restructure dict/object branching, Optional narrowing |
| `service_main.py` | 1 | None guard for `_a2a_registry` |
| `deepgram_sagemaker_tts.py` | 5 | `# type: ignore[union-attr]` for SDK union types |
| `sagemaker_credentials.py` | 2 | Annotate resolver list, fix ShapeID key type |
| `session_tracker.py` | 1 | Type annotation for `_get_dynamodb()` |
| `transfer_tool.py` | 1 | None guard for `context.transport` |
| `discovery.py` | 2 | `# type: ignore` for aioboto3 async context manager |
| `orchestrator.py` | 2 | Cast function list, conditionally include `context_strategy` |

### Phase 2: Developer Experience
- Added pyright to dev dependencies
- Documented zero-error expectation in AGENTS.md

## Files Changed

### New Files
- `pyrightconfig.json`

### Modified Files (12)
- `app/flows/transitions.py`
- `app/flows/flow_config.py`
- `app/flows/nodes/orchestrator.py`
- `app/observability.py`
- `app/service_main.py`
- `app/services/deepgram_sagemaker_tts.py`
- `app/services/sagemaker_credentials.py`
- `app/session_tracker.py`
- `app/tools/builtin/transfer_tool.py`
- `app/a2a/discovery.py`
- `requirements.txt` (pyright dev dependency)
- `AGENTS.md`

## Quality Gates

### QA Validation: PASS
- `npx pyright`: 0 errors, 0 warnings
- All existing tests continue to pass
- No functional changes to application behavior

### Security Review: PASS
- Type fixes only -- no behavioral changes
- None guards add safety against null pointer access in production
- No new dependencies beyond pyright (dev-only)
