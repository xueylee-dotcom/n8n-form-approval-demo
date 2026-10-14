# Local n8n submission-deduplication sample

By **Evan Reed**. Authored sample files are available under the [MIT license](LICENSE); dependencies retain their own licenses.

One workflow tests six contracts: approve a new submission, stop an identical replay, reject without writing, wait without writing, reject an invalid ID, and report changed content under the same ID as a conflict.

Scope: sequential local n8n 2.35.7, synthetic `example.test` data, Python/SQLite mock CRM and scripted approval decisions. This does not verify human identity, concurrency, exactly-once delivery, email-based contact merging, a real CRM or Cloud. An unknown real CRM write outcome must be reconciled or handled using verified destination idempotency, not blindly retried.

## Files and dependencies

This repository includes authored scripts, workflow JSON, synthetic input examples, dependency declarations/lockfile and selected test summaries. **It does not include Node.js, Python, installed npm packages, native binaries, caches, databases, passwords or raw execution logs.** Third-party packages remain under their own licenses; see [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).

The workflow maps public `submission_id` to the mock's internal `request_id`. The two names identify the same submission. It is delivered inactive, with a fixed workflow ID intended only for the temporary test database. Its inherited draft-era “UNTESTED” name is historical; consult the dated test summaries for what was actually checked.

## Prerequisites

The installation procedure targets **macOS ARM64**, with these tools already available:

- Node.js **22.22.0** and npm **10.9.4**
- Python **3.12.3**, standard library only
- Outbound access to `registry.npmjs.org` and the official `TryGhost/node-sqlite3` GitHub release download
- Enough temporary disk space: the installed dependencies alone were approximately 2.2 GB in the original environment; download/cache space is additional

This is a clean **project-dependency** installation procedure, not instructions to install or upgrade system tools. Other operating systems, CPU architectures and Node versions have not been validated. Stop if prerequisites are missing; do not upgrade a shared machine or disable TLS/security settings to make the sample run.

Existing installed `node_modules` are not an npm offline installation cache. A fresh offline install requires every needed package archive and the native dependency; the original environment's cache was incomplete.

## Install in a new working copy

Run the following from the repository directory in a dedicated shell. These environment values apply only to that shell and its children; they do not edit system configuration. No global npm install is used.

```bash
node --version
npm --version
python3 --version

export npm_config_userconfig=/dev/null
export npm_config_cache="$PWD/.install-cache"
export npm_config_maxsockets=4
export NODE_OPTIONS=--max-old-space-size=768
export UV_THREADPOOL_SIZE=2

npm ci --prefix n8n-local \
  --registry=https://registry.npmjs.org \
  --ignore-scripts --omit=optional --no-audit --no-fund \
  --fetch-retries=1 --fetch-timeout=30000
```

The supplied lockfile pins the dependency tree. Lifecycle scripts are deliberately skipped. Do not substitute `npm install n8n@latest`: that is a different runtime with potentially different requirements.

SQLite needs one native binding. Fetch its official prebuilt binary without invoking the install script's source-compilation fallback:

```bash
(
  cd n8n-local/node_modules/sqlite3
  node ../prebuild-install/bin.js --runtime=napi --verbose
)

node -e "require('./n8n-local/node_modules/isolated-vm'); require('./n8n-local/node_modules/sqlite3'); console.log('Required native modules load');"
```

For the locked SQLite 5.1.7 on macOS ARM64, the prebuild source is the package-declared official release:
`https://github.com/TryGhost/node-sqlite3/releases/download/v5.1.7/sqlite3-v5.1.7-napi-v6-darwin-arm64.tar.gz`.

If either step fails, stop and retain the error for inspection. Do not run a global install, replace locked versions, disable certificate verification or install a compiler as an unrecorded workaround. Any newly downloaded dependencies and binaries stay outside the distributable source archive.

## Run the existing bounded test

Ensure loopback ports **8765**, **18765** and **18766** are free. Do not stop unrelated services to free them.

```bash
python3 scripts/n8n_contract_test.py
```

The harness imports/exports the workflow into a fresh temporary n8n database, activates it only in that local instance, submits the form and scripted approval decisions, then shuts down its services and removes temporary runtime data. It does not create a login password or API key. No public listener or tunnel is needed.

Expected outcome: six `PASS` lines across five n8n executions. Pending and approved are two checkpoints in the first execution. Invalid input should end with HTTP 400 at Reserve; conflicting content should end with HTTP 409. Those execution errors are intended test results, not successful CRM writes. Check `evidence/contracts-v3/results.json` for the individual assertions and `result: "PASS"`.

The broad retry setting repeats deterministic 400/409 failures before stopping. This is a local-demo limitation, not a recommended production retry policy. The mock's transaction and stored result also do not establish safe retries against a remote CRM.

## Outputs, privacy and cleanup

The authored harness writes new raw logs under `evidence/contracts-v3`. They can contain the executing machine's local paths. **Do not publish or repackage that generated folder without another redaction review.** Only the preselected summaries originally supplied in this repository are cleared by the included scope-limited scan.

Rerunning overwrites that generated folder's files; preserve a copy if needed. On normal completion, n8n and the adapter stop and temporary runtime data is removed. Installed project dependencies and the selected npm cache remain in the working copy until you intentionally remove that copy. They must not be included when preparing a distributable archive.

Read `VERIFICATION.md` for the actual fresh-install result and any remaining gaps. No account registration or cloud purchase is required for this local sample.

## Download and integrity

Use GitHub’s **Code → Download ZIP**, or clone this repository, and extract it into a new working directory. Before installing dependencies, verify the distributed files with `shasum -a 256 -c SHA256SUMS`. The manifest covers the supplied files except itself. Generated runtime output is excluded from the manifest.
