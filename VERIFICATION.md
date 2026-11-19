# Compartment verification

## Mac 0.2.1 · Inbox and workspace redesign

The Apple silicon app launched on macOS 27.3 with a local sample conversation for each department. In a separate test instance, the operator selected Quality, typed a question, connected to a disposable 0.2 control service, and sent the retained draft. The worker recorded a completed reply from `quality-rep` using `qwen3:4b-instruct`. The reply appeared in the window. The Departments screen displayed five departments with five identities apiece. The sample, live conversation, and roster captures in `examples/` came from running SwiftUI windows.

All six Swift tests passed with the live model enabled. All nineteen control tests passed. The downloadable development app is ad hoc signed. Microphone recognition, audible playback and VoiceOver still require a hands-on device check.

## Version 0.2.0 · Native Mac and Representative messaging

On November 19, 2026, the SwiftUI application built for arm64, launched on macOS 27.3 and connected to an authenticated loopback control service. The Mac app targets macOS 14 and later. The live chat check used a temporary SQLite store, a separate worker and local Ollama running Qwen3 4B Instruct. The earlier PostgreSQL and Compose results below belong to version 0.1.0.

| Check | Observed outcome |
|---|---|
| Native sign-in and routing | The running app showed five department Representatives in its sidebar, loaded a private conversation after sign-in, and displayed a live-model reply. A synthetic message submitted through the native composer reached the selected Planning Representative. |
| Live conversation | The Swift client saw 25 identities in five departments. Planning remembered “Silver Birch” across two turns. Quality answered a separate question without the Planning turns appearing in its transcript. The server supplied the speaker identity and model identifier for each result. |
| Native regression suite | Six tests passed with live chat and speech synthesis enabled. Four cover transport restrictions, supported addresses, exact approval payloads and decoding an exported Assurance Graph. |
| Control-plane regression suite | Nineteen tests passed. Chat coverage includes duplicate submissions, idempotency-key conflicts, recipient validation, viewer restrictions, pending-turn queuing, preview isolation, and private run exclusion. |
| Mac packaging | The bundle uses hardened runtime, App Sandbox, outbound networking, audio input and user-selected file access. It includes usage descriptions and a privacy manifest. The downloadable binary is ad hoc signed for local development. |
| Voice | The composer uses Apple Speech with required on-device recognition and explicit Send. Apple speech synthesis rendered a synthetic Representative reply into a non-empty PCM audio buffer. Hands-on microphone capture, end-to-end dictation, audible playback and VoiceOver remain device acceptance checks. |

The native inbox preview is in `examples/mac-inbox.png`. It shows the packaged application displaying the Quality Representative’s live response to a synthetic operator question. Model responses are advisory. Public Mac distribution still requires Developer ID signing and notarization. The minimum supported OS and Intel hardware have not been exercised.

## Earlier 0.1.0 harness verification

Verified November 19, 2026. The release contains one executable integration-audit playbook. The live demonstration used local Qwen agents for meeting turns and a bounded specialist-advice request. Deterministic code performed assignment transitions, browser and contract checks, authorization, and acceptance checks. Test clients used operator credentials to exercise the human decision paths.

## Deployment results

| Deployment | Observed result |
|---|---|
| Clean ARM64 Linux VM, Docker Engine 29.10.0 and Compose 5.8.0 | Built images from source, started PostgreSQL, control, worker, Chromium lab and ticket service. The default fixture-mode audit completed with 25 identities. |
| Separate Compose project with cloud overlay | Restored a signed snapshot into new database and artifact volumes. The accepted run’s manifest and every evidence file matched the source bytes. A fresh operation completed over TLS with a locally trusted Caddy certificate. |
| Native PostgreSQL 16.2 with a live model | Qwen 3 4B Instruct contributed attributed meeting positions and scoped peer advice. The accepted example contains 74 lineage nodes and 121 edges. A second PostgreSQL cluster restored the same records and completed another live-model audit. |
| Browser console | Headless Chrome signed in, opened the roster, created an audit, resolved Pushback, approved a ticket, accepted the result, inspected QA evidence, and downloaded the ZIP. The mobile-width check passed at 390 CSS pixels. |

Container verification used PostgreSQL 16.16, Chromium 156.0.8078.79 and Caddy 2.11.9. Public DNS issuance and a customer's cloud account were outside these runs.

## Mandatory scenarios

| Scenario | Evidence |
|---|---|
| Contradiction | Source requirements appeared verbatim. The ticket stayed blocked while the browser inspection and independent QA proceeded. A separate regression tested a source-indexed model challenge to apparently consistent structured rules. |
| Delegation loop | The engine stopped an ancestor loop and a separate cross-task wait cycle. Depth and fan-out bounds generated recorded escalations. |
| Approval bypass | Altered parameters, worker credentials at an operator endpoint, wrong-tool capabilities, and a revoked tool permission all failed. Approved sandbox dispatch succeeded. |
| Crash recovery | The test killed the actual HTTP control process before dispatch, then again after the external service committed and before the control transaction committed. Recovery required reconciliation. The external target contained one matching ticket. The test advanced the lease deadline to shorten the wait. |
| Independent acceptance | The original producer checked field presence and missed a type error. A QA identity re-read the original source, caught it, and verified the corrected report. Both verdicts survive export. |
| Cost and isolation | Concurrent workers contested claims. Separate model reservations enforced slot and spend limits. Tests denied unauthorized project, department, meeting-context, role and tool access. An additional service-level test forced an unavailable HTTP route and completed the same advice assignment through the approved live local fallback. Charges are operator-defined upper bounds. |
| Portability | Native PostgreSQL and Compose restore checks passed. The Compose check compared every byte in the exported manifest and evidence files and ran a fresh operation behind the cloud proxy. |
| Department meeting | Two Representatives and a Director generated attributed minutes, dissent, timed follow-up and a continuing operator decision. The meeting could not authorize ticket creation. |

The focused suite contains 18 passing tests. The TypeScript check and production Vite build passed. The complete native and Compose test records are supplied with the release examples.

## Evaluation and learning

Four synthetic cases exercised type drift, compatible data, a missing field, and contradictory instructions. Each arm used eight calls to the same local model, identical per-call output ceilings, the same fixture evidence and the same adjudication rubric.

| Arm | Correct decisions | Conflict recall | False-positive rate |
|---|---:|---:|---:|
| Single agent | 1 / 4 | 1.0 | 1.0 |
| Multiple agents without Pushback | 1 / 4 | 1.0 | 1.0 |
| Compartment with deterministic assurance checks | 4 / 4 | 1.0 | 0.0 |

The assurance arm explicitly applies a contract checker and structured requirement comparison. These four cases exercise those controls. The scores establish no general performance advantage. The first trial used unconstrained JSON and failed two assurance cases. Its results remain in `tests/results/initial-evaluation.json`. All arms were rerun with the same structured output schema. The promotion command rejected the initial evaluation and accepted the final one.

## Operating boundaries

- The distribution ships an Inventory v2 sandbox, one scoped Chromium read, one fixed Python checker, and one idempotent ticket adapter. New production targets need their own contracts, authorization, evidence and recovery tests.
- Connector scope, data access, spending reservations and schedules are controlled locally. The live-model evidence covers a local OpenAI-compatible endpoint. Vendor invoices, long-running load, customer error rates and retention require field measurement.
- The release demonstrates the local and cloud deployment profiles inside a disposable VM. Public-cloud network policy, public certificate issuance, external secret management and disaster recovery procedures remain operator deployment responsibilities.
- Audit integrity depends on protecting the audit key and retaining a trusted checkpoint or backup. Local memory expiry removes active records. Operators also control the retention and deletion of copies they export.
