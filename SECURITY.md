# Security policy

## Reporting a vulnerability

Report suspected vulnerabilities privately to **security@corsen.ai**. Do not
open a public issue containing an exploit, pairing code, session token, browser
profile, or private page content. If GitHub private vulnerability reporting is
available for this repository, its private reporting form is also suitable.

Include the affected extension and companion versions, operating system,
browser version, expected behavior, actual behavior, and minimal reproduction
steps using a disposable profile and synthetic data. State whether the issue
requires local access, an attached tab, or an authenticated companion.

Keep credentials and personal information out of logs and screenshots. If a
credential may have been exposed, revoke or rotate it rather than posting it.
Coordinate disclosure and remediation privately before publishing details.

## Supported versions

Security fixes target the latest stable release. The extension and companion
must be a matching supported pair. The development branch is not a substitute
for a published and validated release. Older versions may require upgrading.

## Boundaries to preserve

- The dashboard and companion connections remain restricted to loopback.
- Browser access is limited to the exact profile/session and tabs selected by
  the user. Selecting a different browser tab must not silently transfer access.
- Pairing credentials and dashboard session tokens must not appear in tool
  results, public logs, release archives, or third-party requests.
- Asynchronous responses from an older connection, tab binding, or selected
  session must not authorize actions or replace a newer selection.
- Tests and installers must not modify a developer's real browser profile or
  an unrelated Hermes installation during automated validation.

Local software running with the same account privileges can access resources
that a browser extension cannot protect from that account. Likewise, content
on an authorized page remains untrusted input to the agent; tab authorization
is not a guarantee that the page's instructions are trustworthy.

## Release checks

Run the complete release gate, platform installer tests, and packaged-browser
acceptance before publishing. Review the actual CodeQL findings, not only the
workflow conclusion. A passing test suite does not prove the absence of all
vulnerabilities.
