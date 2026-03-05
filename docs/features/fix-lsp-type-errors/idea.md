---
id: fix-lsp-type-errors
name: Fix LSP Type Errors
type: Tech Debt
priority: P1
effort: Medium
impact: High
created: 2026-03-05
---

# Fix LSP Type Errors

## Problem Statement

The codebase has accumulated multiple LSP (Language Server Protocol) type errors across the voice agent pipeline. These are not cosmetic warnings -- they indicate real type mismatches that mask potential bugs and erode confidence in the type system. When the type checker is noisy with false positives and ignored errors, real regressions slip through unnoticed.

Currently observed errors include:

1. **InterimTranscriptionFrame / TranscriptionFrame mismatch** (lines ~626, ~638): `InterimTranscriptionFrame` is passed where `TranscriptionFrame` is expected in `_handle_transcription`. This is a union type issue -- the handler needs to accept both frame types or the call sites need narrowing.

2. **dict attribute access for `.channel`** (lines ~674-687): Code accesses `.channel` on a value typed as `dict[Unknown, Unknown]`. This suggests a missing type annotation or an untyped deserialized payload that should be given a proper dataclass or TypedDict.

3. **None attribute access** (lines ~443, ~457): Attributes `stt_latency_ms` and `llm_ttfb_ms` are accessed on a value that can be `None`, and `>=` is used on a potentially `None` value. Missing null guards or Optional narrowing.

These are the errors we know about today. A full audit will likely uncover more.

## Proposed Solution

1. **Audit**: Run pyright/pylance across the full `app/` directory and catalog every error and warning.
2. **Fix systematically**: Address each error category:
   - Add `Union[TranscriptionFrame, InterimTranscriptionFrame]` or a common base type to handler signatures
   - Replace raw `dict` access with typed dataclasses or TypedDict for transport/channel payloads
   - Add proper `Optional` narrowing (`if x is not None`) before attribute access
   - Fix any additional errors found during the audit
3. **Prevent regression**: Establish the expectation that LSP errors are treated as defects. Any new LSP error introduced in a change should be fixed before merging. Consider adding a pyright check to CI.

## Affected Areas

- `app/pipeline_ecs.py` -- transcription handler, metrics tracking, transport channel access
- Potentially other files under `app/` once full audit is complete

## Success Criteria

- Zero pyright errors in the `app/` directory
- Type checker runs clean with strict mode on core modules
- New code does not introduce type errors (enforced by review discipline or CI)

## Notes

- Supersedes the narrower `cleanup-lsp-errors` feature (P2/Small/Low) which only covered 3 errors in pipeline_ecs.py
- Runtime behavior is correct today -- these are static analysis issues -- but ignoring them means the type checker cannot catch real bugs
- Some fixes may require upstream type stubs for pipecat if its public API is untyped; in those cases use `typing.cast()` with a comment explaining why
