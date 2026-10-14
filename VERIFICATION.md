# Verification record

Verified on **14 October 2026**, macOS ARM64, with existing Node 22.22.0, npm 10.9.4 and Python 3.12.3. The n8n version is fixed at 2.35.7. This establishes a clean project installation on that environment, not a fresh operating-system setup or portability to other platforms.

## Installation test

A new independent temporary directory received the candidate source, workflow, fixture and lockfile. No existing `node_modules` was copied or linked, and no global package was installed. The procedure used the README's locked `npm ci` flags, then SQLite's official prebuild command and native-module load check. The verification used an empty temporary sibling npm cache; the README uses a cache within the reader's working copy. Both are isolated caches and do not change the dependency tree.

The original environment's existing npm cache was insufficient for an offline fresh install. This verification therefore downloaded the locked dependencies from the official registry, and the SQLite native binding from its package-declared official release. No new dependency versions were introduced. The lockfile remained byte-identical.

All four steps exited 0:

1. Clean locked npm installation, with lifecycle scripts disabled and optional dependencies omitted.
2. SQLite 5.1.7 prebuilt binding download; no source-compilation fallback.
3. Required native modules loaded successfully.
4. The existing n8n contract harness completed successfully.

## Runtime result

**Six checks passed across five sequential n8n executions:**

| Check | Observed result |
|---|---|
| Pending approval checkpoint | Waiting; no contact or commit call |
| New submission approved | One contact and one write |
| Identical replay | No extra record, write or approval |
| Rejected submission | No CRM write for that submission |
| Invalid ID | HTTP 400; execution error before any CRM write |
| Same ID with changed content | HTTP 409; manual-review message; original data unchanged |

These are the same bounded checks, not new product features or an expanded test suite. Approval decisions were scripted. The selected results are in `evidence/clean-install-summary.json`; the earlier baseline result is separately retained in `evidence/test-summary.json`.

The fresh runtime reported zero credential entries and zero users with a password. n8n exited normally with code 0, its runner and mock adapter stopped, and all three loopback ports subsequently refused connections. Temporary runtime data and the separate clean-install dependency/cache directory were removed. The original workspace and its installed dependencies were retained.

## Candidate contents and privacy scope

This candidate is source/configuration/documentation only. It contains no installed dependencies, native executables, databases, caches, raw logs, error stacks, resume URLs, account passwords or credential exports. Summaries were constructed by selecting known non-sensitive fields, not by distributing raw execution data with a few string replacements.

The filename and text scan checks for private host paths, the local owner's identity, credential/private-key patterns and unexpected email addresses. The workflow contains no credential-reference fields. One public maintainer email in upstream lockfile deprecation metadata is an explicit metadata exception; it is not a user/customer address. This targeted packaging check is not a comprehensive security audit of third-party packages.

Generated logs from a user's later run may contain that user's local paths. They are not covered by this candidate scan and must not be redistributed without a fresh review.

## Limitations

- The install requires network access and the stated existing system tools; a self-contained offline installation is not provided.
- Other architectures, operating systems and runtime versions are untested.
- Real human authorization, concurrent submissions, a real CRM, unknown-write reconciliation, recovery, production deployment and Cloud comparisons remain untested.
- The inherited broad retry setting repeats 400/409 responses before stopping; it is not a production retry recommendation. Known unused-node/Python-runner and dependency-deprecation warnings were not treated as a reason to install more components.

These observations support only this bounded local sample. They do not establish production readiness or a Cloud performance comparison.
