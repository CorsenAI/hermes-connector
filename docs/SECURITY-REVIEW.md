# CodeQL findings: corrections and regression coverage

This change follows the snapshot escaping correction in pull request #12. It
preserves the HMAC algorithm, role/identity/nonce input, protocol version,
Chrome permissions, runtime dependencies and credential storage.

## Pairing authority

The pairing proof remains mandatory. A missing connection nonce or a proof
unequal to the locally calculated HMAC invalidates the session, closes the
socket and returns from the message handler. A missing proof is rejected by
the same strict comparison; a separate truthiness check is unnecessary.

The broker must also return literal `ok: true`. Strings, numbers, objects and
a missing success flag cause the same fail-closed exit. Authority is assigned
locally only after both checks. The HMAC covers the role, browser identity and
nonce, not every message field. Early returns make rejection terminate the
handler explicitly rather than relying on a switch `break`.

## Keyboard authority

An absent or null reference means the active element. A supplied reference
must be a non-empty string; invalid values fail instead of falling back to an
unrelated focused field. In the CDP path, authorization is checked before and
after optional focus regardless of whether a reference was supplied. Failed
focus still aborts. The CDP key dispatch keeps its authorization callback,
including revalidation after asynchronous debugger attachment.

## Wait bounds

`boundedWaitMs` accepts only finite numbers, with absent/null mapped to zero.
It returns zero for negative input, 15,000 for larger input, and the requested
value only on the path bounded by those comparisons. It never returns an
unvalidated or non-finite delay. Normal delays and the companion's separate
1,000 ms default remain unchanged. Numeric strings, booleans, arrays, objects
and non-finite numbers are rejected rather than coerced.

The serialized action queue remains limited to 32 pending actions. Revocation
invalidates authority; it does not instantly cancel a running timer. The
post-wait authorization check prevents stale results and actions from crossing
into a replacement session.

## No JavaScript finding exemptions

The earlier full analysis of commit
`044fc4ef29f14874c77709fe1a8774f215ee14ee` (run `35037307711`,
CodeQL CLI 2.27.0, security-extended) emitted four JavaScript findings and one
Python finding. The initial source-bound JavaScript dispositions have been
removed. The current implementation uses explicit rejection and unconditional
authorization paths instead. Any high/critical JavaScript finding now blocks
the gate; no JavaScript rule is disabled and no result is filtered.

The full push analysis, not only a diff-informed PR check, must verify the
updated sources. Reports include the exact source revision and tracked source
archive. Test and analysis conclusions are recorded against their commit in
the pull request; a source change requires fresh validation.

## Intentional pairing-code output

The Python clear-text-output finding is **not claimed fixed or dismissed**.
`broker.py --show-code` intentionally returns the full secret to its caller,
including the installer's captured subprocess. Restricting all non-terminal
output would break that contract. Ordinary broker startup logs its listening
address, not the pairing code.

The remaining exposure, safe handling and the existing installer
`--no-show-code` option are documented in `hermes-plugin/README.md`. File
permissions do not protect copies retained in terminal recordings or logs.

This is the only entry in `.github/codeql-reviewed.json`. Its rule ID, score,
source location, complete broker source, installer and output tests are pinned
to the reviewed bytes. Changes invalidate the disposition. The finding and
real severity remain in SARIF and GitHub; this is a documented intentional
exposure, not a claim that secret output is risk-free. Unknown severity,
analysis errors and unreviewed high/critical findings remain blocking.

## Verification

`tests/background-security.test.mjs` executes production background, HMAC,
binding and CDP code in a fresh child process for each of 36 scenarios. Only
browser APIs, WebSocket delivery and selected timer scheduling are simulated.
The matrix covers proof acceptance/rejection/replay, malformed success flags,
optional and invalid keyboard references, revocation during focus/attachment,
wait bounds, queue saturation and reconnect recovery.

`tests/test_pairing_output.py` verifies the explicit stdout contract, real
subprocess capture using temporary credentials, mutually exclusive CLI modes
and normal startup output. `tests/test_codeql_report.py` tests extension/driver
rule resolution, malformed metadata, unknown scores, analysis errors, blocking
exit codes and invalidation of source-bound reviews.

All pre-existing tests and the authenticated packaged-browser snapshot test
remain enabled. The snapshot test includes an old-code negative control that
must reach the snapshot and reproduce the expected escaping failures.
