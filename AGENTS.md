# AGENTS.md

Instructions for agents working on qvf. Read [CONTRIBUTING.md](CONTRIBUTING.md)
for setup and the contribution workflow.

## Keep this repository public-safe

This product repository must remain ready for public mirroring at every commit.

- Never put private email addresses, real machine names or host aliases,
  internal hostnames or URLs, private IP addresses, account names, personal
  filesystem paths, credentials, tokens or site-specific deployment details
  in tracked files, filenames, generated artifacts or commit messages.
  This includes code, comments, tests, documentation and agent instructions.
- `project@vibe-qc.com` and `mpei@vibe-qc.com` are explicitly allowed public
  email addresses. Use generic placeholders and reserved example addresses
  for tests and documentation; do not copy real private values into fixtures.
- Keep private configuration separate from product code. Store it outside
  the product checkout on the local machine, or in the private agentic loop
  repository. Select it through environment variables, command-line options
  or an explicit external configuration path. Commit only portable defaults,
  schemas and examples without private values.
- Ignored files and custom folders under `.git` are not private configuration
  stores. Keep private operational logs, inventories and release evidence
  outside the product checkout too. Never commit secrets to the private loop
  repository; use the existing credential or secret store.
- Prevent contamination while making the change. Inspect the diff and use the
  existing automated privacy checks before committing. Fix a finding in the
  source; do not rely on a later sanitizer or create sanitation chats for
  routine releases. Never bypass a privacy failure to publish a release.

