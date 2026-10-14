# License scope and third-party dependencies

The authored sample scripts, workflow configuration, synthetic fixtures, documentation and selected test summaries are licensed under the root MIT LICENSE, copyright 2026 Evan Reed.

The workflow references n8n built-in node types; it does not include their implementation. The npm package declaration and generated lockfile identify separately downloaded dependencies, registry locations, integrity hashes and upstream metadata. A public maintainer email occurs in upstream deprecation metadata.

n8n, SQLite, isolated-vm and all other dependencies retain their respective licenses. The sample's MIT license does not relicense them. No dependency source, installed package tree, native binary or cache is included. Consult the license files in the separately installed packages before using or redistributing them. The pinned n8n package declares `SEE LICENSE IN LICENSE.md`.

`scripts/n8n_engine_test.py` contains helpers used by the contract harness; its older standalone test entry point is outside the README's recommended run. The contract harness creates missing parent output directories to support a fresh working copy. The tested workflow and mock business logic are unchanged.
