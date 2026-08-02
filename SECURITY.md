# Security policy

## Supported version

Security fixes target the latest release on the default branch.

## Reporting

Do not open a public issue containing credentials, private URLs, browser state,
or exploitable details. Use GitHub's **Report a vulnerability** form (private
vulnerability reporting) for this repository. If that feature is temporarily
unavailable, contact a maintainer privately without attaching live credentials
or personal browser data.

## Deployment assumptions

This project is designed for one local user. MCP and configured SearXNG endpoints are restricted to loopback and provide no application-layer authentication. A network deployment requires a separately designed authenticated and encrypted boundary; changing this source policy is not sufficient by itself.

Web content is adversarial input. The service separates it from answer instructions, detects prompt-injection markers for advisory diagnostics, rejects private-network crawl targets, and never uses a personal browser profile. Detection is not filtering; the primary controls are evidence boundaries, sanitized output, and the default answer-only MCP tool surface.

The default MCP process publishes only `research`. Diagnostic and administrative tools keep their stable names but require an explicit `--toolset diagnostic` or `--toolset admin` process. Never connect a general answer agent to an elevated process.

Never commit `.env`, databases, model caches or binaries, browser profiles or
storage, logs, or captured pages. Build release archives, then run
`uv run python scripts/check_release.py --artifacts dist`; the default check
inspects the current tree and filenames across every Git ref. This is not a
substitute for an independent secret scanner. If a secret was ever committed,
removing the current file is insufficient: rotate it first, then rewrite all
affected history before making the repository public.

CAPTCHA outcomes are classified as terminal and are never solved or handed off for interactive completion. Authenticated crawling, paywall bypass, persistent cookies, personal browser profiles, and write-capable browser automation are out of scope.
