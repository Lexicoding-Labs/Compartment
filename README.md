# Compartment

Compartment runs a scoped integration audit through five departments and 25 persistent agent identities. An operator can follow a disputed requirement from its source through a meeting, independent reproduction, approval, sandbox action, and verified report.

## Start locally

Install Docker with Compose 2.24.4 or later and Python 3. Run these commands from the extracted project.

```sh
python3 ops/configure.py
docker compose up --build -d --wait
```

Open **Compartment.app** on the Mac and connect to `http://127.0.0.1:8080`, or use the browser console at [localhost:8080](http://localhost:8080). Sign in with the value of `OPERATOR_TOKEN` in the generated owner-readable `.env`. The configuration command refuses to overwrite existing credentials. PostgreSQL, artifacts, and sandbox tickets use named volumes. `docker compose stop` stops services and preserves state.

Choose **New audit → Start audit**. The Planning Director allocates scoped work. A Research Specialist inspects Inventory v2 in a browser. An Execution Specialist asks a different Research Specialist for advice. Representatives discuss ticket timing and bring in the Quality Director. Pushback quotes the incompatible requirements while the read-only work continues.

Open **Meetings** to inspect attributed positions, dissent, and the follow-up assignment. Choose whether to request a ticket or omit it. Choosing a ticket exposes a separate approval for its exact target and parameters. In **Evidence**, compare the original report, rejected review, corrected report, and final verification. The sampled response returns a string for the integer field `available`. Accept the reviewed audit and download its evidence archive.

The default installation uses reproducible fixture responses for meeting and advice turns. Chromium, the scoped Python contract checker, PostgreSQL, the external sandbox ticket service, and the approval boundary execute in both modes.

## Message a department on macOS

The Mac application targets macOS 14 or later. The 0.2.1 Mac app opens in a local sample workspace. Select a Representative to explore an illustrative conversation, then choose **Connect** to join your own server. Drafts stay in the composer through sign-in and require Send. Screenshots of the sample inbox, a live Quality conversation and the roster are included under `examples/`. The prebuilt app runs on Apple silicon. Extract the Mac ZIP and open Compartment.app, or build the application from source with a Swift 6 Apple toolchain using `./script/build_and_run.sh`. The development build is ad hoc signed. Connect it to version 0.2 of the control service. Use HTTPS for a remote server. The token stays in memory and disconnecting clears unsent drafts.

Choose the Planning, Research, Execution, Quality, or Reliability Representative in the sidebar. Each has a separate conversation and message preview. Type a message and press **⌘Return**, or select **Dictate**. Stop dictation, edit the transcript, and press Send. macOS requests microphone and speech-recognition permissions on first use. Dictation requires an available on-device recognizer for your language. Only submitted text goes to the control service. In the composer’s speaker menu, enable **Speak New Replies**, or use **Read Aloud** on an individual response.

Representatives answer under their configured role, worker limits and model route. The worker supplies up to six completed turns from the same operator’s thread as context. Live conversation uses the **advice** capability below. The default fixture identifies itself in each reply. Chat is advisory. Use **Operations** to start an audit, resolve an official Pushback case, approve an exact action, or accept and export a report. Self-hosted database backups contain saved conversations and require the same access controls as the deployment.

The app opens in dark appearance. Choose **Settings → Appearance** for Light or System. The Workspace disclosure contains Operations, Departments, Schedules and Governance. The application uses native split navigation, labeled keyboard-accessible controls, an App Sandbox entitlement, and a user-selected file exporter. The reference interaction uses Apple’s [macOS design guidance](https://developer.apple.com/design/human-interface-guidelines/designing-for-macos), [accessibility guidance](https://developer.apple.com/design/human-interface-guidelines/accessibility), and [Speech framework](https://developer.apple.com/documentation/speech).

Run the Mac transport and decoding tests with `./script/test_mac.sh`. To exercise the optional live test, set `COMPARTMENT_TEST_ORIGIN` and `COMPARTMENT_TEST_TOKEN` to a dedicated test account on a disposable Qwen-enabled deployment. The test sends three synthetic messages across two departments and checks the Planning follow-up against its previous turn.

## Live agents

Use an OpenAI-compatible chat-completions endpoint reachable **from the worker container**. Meeting turns use structured JSON output. Add the following settings to `.env`, substituting a deployed model name and reachable endpoint, then run `docker compose up -d`. These examples use a local, unbilled model. For a metered endpoint set a conservative upper-bound charge per call in micro-US dollars.

```dotenv
MODEL_ROUTES='[{"name":"local","model":"qwen3:4b-instruct","capabilities":["meeting","advice"],"charge":0,"budget_microusd":100000,"timeout_s":90}]'
MODEL_ENDPOINTS='{"local":{"url":"http://host.docker.internal:11434/v1"}}'
```

For a provider requiring authentication, add `"key_env":"PROVIDER_API_KEY"` to its endpoint and supply that secret to the worker. A second approved route can use `FALLBACK_API_KEY`. Route order defines fallback order. An optional `agents` list limits a route to named identities. The control plane reserves the declared amount before issuing a live claim and retains conservative charges when a provider outcome is uncertain. The displayed reservation is an accounting ceiling. Provider billing reconciliation requires the provider’s billing data.

The console shows **live** or **fixture** beside the signed-in identity. The initial worker process handles one claim at a time. To exercise parallel workers, run `docker compose up -d --scale worker=3`. Global worker slots, departmental quotas, and live-model slots apply independently.

## Web console and API

| Surface | Operator actions |
|---|---|
| Operations | Start, pause, resume, cancel, checkpoint, resolve Pushback, approve the exact ticket, reassign or retry eligible tasks, reconcile uncertain effects, accept, and export. |
| Departments | Inspect the five positions in each department, edit an identity’s versioned instructions and tool allowlist, and mark absences. The API also supports time-limited acting appointments and department configuration. |
| Schedules | Create recurring operations, inspect next-due times, pause, and resume. The API supports meeting schedules and authenticated, deduplicated event triggers. Missed intervals coalesce into one execution. |
| Governance | Inspect and edit worker, model, spend and tool policies. Emergency stop pauses active runs and fences their leases. Resumption requires separate operator action. |

The versioned API begins at `/api/v1`. Local interactive API documentation is available at `/docs`. Use an `Authorization: Bearer …` header. Configure additional human accounts in `OPERATORS` as a JSON array of objects with `name`, `project`, `role`, and a unique random `token` of at least 24 characters. Roles are `admin`, `operator`, and `viewer`. Use a common project for collaborators who should see the same runs. Optional `department`, `agent`, and `tasks` fields grant specific knowledge scopes. Changes to policy and identity configuration require an administrator.

The audit playbook handles natural-language objectives through a scope check and accepts structured ticket requirements through the runs API. Each rule includes its verbatim text, an `effect` of `open` or `hold`, and a `when` of `finding` or `review`. Model participants can challenge semantic inconsistencies by citing particular requirements. Policy decisions and tool grants run in application code. An operator may preauthorize omission of unspecified ticket work using `missing_ticket: "omit"`.

## Deployment and recovery

The local profile binds the console to loopback. For an always-on server with DNS pointing to it, set `COMPARTMENT_DOMAIN` and start the cloud overlay.

```sh
docker compose -f compose.yaml -f compose.cloud.yaml up --build -d --wait
```

The overlay removes direct publication of the API port. Caddy serves HTTPS, redirects HTTP, and filters internal worker endpoints. The browser lab has its own private network, read-only image, temporary browser profile, resource limits, and a fixed executable inventory. The ticket service has a separate network and volume. Only the control service holds both dispatch authority and the ticket credential. The reference runtime accepts a named inventory URL and a fixed contract checker. Extending the tool inventory requires implementing and testing an explicit adapter.

Create a portable backup from a running control service.

```sh
docker compose exec -T control python -m compartment.backup backup /backup/release.zip
docker compose cp control:/backup/release.zip ./release.zip
```

For restoration, use a **fresh Compose project** with empty database and artifact volumes. Preserve the source deployment’s `AUDIT_KEY` through your secret-management process. Put the archive in the new project directory. The restore command validates the snapshot signature, audit chain, schema version and content digests and refuses a populated target.

```sh
docker compose up -d --wait db
docker compose run --rm --no-deps -v "$PWD/release.zip:/import.zip:ro" control python -m compartment.backup restore /import.zip
docker compose up -d --wait
```

A restored active run starts paused. Schedules start disabled. Reconnect the intended integration target, reconcile outstanding intents, and resume the selected work. The snapshot contains control state and evidence. The ticket target is an external system with an independent lifecycle. Preserve its volume if you need the original sandbox ticket database. Protect snapshots and evidence exports according to the source data’s access and retention requirements.

**Compensation.** Pause and cancellation fence queued and leased work. A request already accepted by an external system can finish. The reference ticket adapter uses the task ID as its idempotency key. An interrupted ticket enters review. Reconciliation queries the external receipt. A confirmed effect completes the task, a confirmed absence requires fresh approval, and an unavailable target keeps the outcome unresolved. Closing an existing external ticket is a separate operator decision. Emergency stop cannot reverse a committed action.

## Evidence, knowledge and evaluation

The accepted ZIP contains `manifest.json` and content-addressed evidence indexed by stable node IDs. The manifest includes typed relationships, origin, access label, requirements, tasks, agent/model/tool versions, review decisions and approvals. Follow a claim back to the original sample and forward to the corrected report or ticket. Hashes verify bytes. The independent contract reproduction establishes the technical finding.

Local memory records carry a source, confidence class, author, access label, and expiry. Search and graph views apply the original permissions. Deletion and expiration remove memory content and its graph edges. Audit records retain digests and actor information. Production services suppress HTTP access logs. The standard playbook captures structured fixture data and keeps screenshot capture off. Local Conflict Atlas entries require explicit operator adjudication and consent through `POST /api/v1/pushback/{id}/adjudicate`. The distribution includes no cross-customer data collector.

Run the offline regressions and optional live comparison from the project root.

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
npm --prefix web ci
npm --prefix web run build
.venv/bin/python -m compartment.evaluate --endpoint http://127.0.0.1:11434/v1 --model qwen3:4b-instruct --output evaluation.json
```

Promote a version to a local portable playbook package with a passing matching evaluation, an accepted evidence bundle, and an explicit operator invocation.

```sh
.venv/bin/python -m compartment.promote playbooks/integration-audit.json reference-evidence.zip evaluation.json verified-playbook.zip
```

For a service-level smoke test, supply the operator credential in the environment and run `python3 ops/smoke.py --url http://127.0.0.1:8080`. It creates and accepts a synthetic operation against the included sandbox. The live release harness additionally needs `pgserver`, a Chromium executable, and a configured model. It starts temporary PostgreSQL clusters, kills a temporary control process at two dispatch boundaries, restores the state, and completes a second operation. See `python tests/live_release.py --help` with `PYTHONPATH=.`.

The source ZIP includes an `examples/` folder with the accepted live evidence archive, baseline results, console preview, and deployment test records. The release evidence and outstanding validation boundaries are recorded in [VERIFICATION.md](VERIFICATION.md).
