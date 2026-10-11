# Beat the Guard

An offline higher-education policy game. Players challenge a ResearchGuard classifier with synthetic evidence; the app scores attempts and presents a booth leaderboard.

**Maturity:** Booth prototype. Synthetic data/mission parsing and core parser, scoring and SQLite game-state smoke checks are covered in this review. Model-backed verdict quality, kiosk controls, Wi-Fi installation and multiclient load were not run.

## How it works

FastAPI serves player/board/admin pages and a SQLite game store. A strict JSON contract wraps a local vLLM LoRA classifier. Abuse limits, per-device/global quotas, consented lead exports and password-protected admin controls support booth operation.

## Getting started

Read [installation, configuration and shutdown](docs/OPERATIONS.md) and [model/data retrieval](docs/MODELS.md). Review [dependency evidence](docs/DEPENDENCIES.md) before choosing an environment. The safe review launcher uses loopback and does not install services or load models.

## Security and data

Read [security and safe updates](SECURITY.md) and [ownership/license status](docs/LICENSE-STATUS.md). Runtime originals are preserved separately. This is a sanitized source snapshot with new history: no account state, business records, model weights, unknown media assets or original logs/history are distributed. Third-party notices included in this copy remain applicable.

## Verification

See [verification evidence and limitations](docs/VERIFICATION.md). Tests distinguish synthetic/mocked workflows from live integrations. Original demo screenshots and document recordings are excluded; use the synthetic workflow in the operations guide for your own reviewed demonstration.

## Roadmap

Add repeatable offline contract tests and adapter provenance receipts; replace booth-specific network setup with explicit deployment profiles; strengthen CSRF/origin checks on administration and verify contact-data retention.

For route/source details see [architecture](docs/ARCHITECTURE.md).
