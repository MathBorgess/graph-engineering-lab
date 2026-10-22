# Voice Lab — bounded voice experiment

The terminal pipeline transcribes audio, runs a deterministic LangGraph router and
synthesizes its response. The operational tools create and cancel **simulated**
jobs in a local SQLite sandbox; they do not launch the laboratory experiments.
No LLM inference is implemented in the conversational router.

## Action safety

An action request creates a pending proposal. Only a new human message containing
a complete explicit confirmation can authorize that proposal. Questions and
conditional replies remain pending. For example, `quero apenas uma simulação`
and `sim, mas explique antes` never authorize an execution.

Consent binds the proposal ID, version, tool name and exact arguments. A changed
proposal requires a new confirmation. The executor accepts only its registered
tool and uses the bound digest as the durable SQLite idempotency key. Retrying
one confirmed proposal returns its original job; a separately confirmed proposal
creates a new job, even with the same arguments. Standalone callers of
`execute_trigger_experiment` must supply a stable `idempotency_key`; an absent key
or a key reused with other arguments fails before mutation.

The sandbox serializes check-and-write operations, including cancellation.
Listing jobs never seeds fixtures. Existing databases remain readable; no rows
are migrated or deleted. Legacy confirmed checkpoints without bound consent
fail closed and require a fresh request/confirmation. These safeguards assume
the local caller is trusted to provide human messages and checkpoint state.
The digest is a consistency check, not a cryptographic identity credential.

## Portable control-path checks

Use an isolated Python 3.12 environment, without audio models:

```sh
python -m pip install -r src/05-voice-agents/requirements-safety.txt
python -m pytest src/05-voice-agents/tests -q
```

The tests exercise the real graph, SQLite checkpoints, independent processes,
concurrent retries, ambiguous consent, changed arguments and side-effect-free
job queries. They do not test microphone permission, transcription, synthesis,
human comfort or production latency. Audio dependencies from `pyproject.toml`
are loaded only when the interactive runner or audio helpers are requested.

The earlier `EXPERIMENT_REPORT.md` is a historical report. Its audio and timing
claims were not remeasured by the safety correction of 2026-10-22. Passing these
tests does not establish a complete voice product or validate those claims.
