# CodeQL findings: scope and regression coverage

This change follows the snapshot escaping correction in pull request #12. It
preserves the HMAC algorithm, role/identity/nonce input, protocol version,
permissions, dependencies and credential storage.

## Pairing and keyboard authority

The pairing proof remains mandatory. The broker must also return the protocol's
literal `ok: true`; strings, numbers, objects and a missing success flag are
rejected. The authenticated state is then assigned locally, not copied from a
message field. The HMAC covers the role, browser identity and nonce, not every
message field.

Keyboard input still requires current session and tab authorization. An absent
or null reference means the active element. A supplied reference must be a
non-empty string; invalid values fail instead of falling back to an unrelated
focused field. Existing focus failures and authorization checks before actual
CDP input remain in place.

## Wait bounds

Wait durations must be finite numbers. Negative values clamp to zero; values
above 15,000 ms clamp to 15,000 ms. Normal numeric delays and the extension's
absent/null default of zero are preserved. The companion's 1,000 ms default is
unchanged. Numeric strings, booleans, arrays, objects and non-finite numbers are
rejected rather than coerced.

The existing serialized action queue remains limited to 32 pending actions.
Revocation invalidates authority; it does not instantly cancel an already
running timer. The post-wait authorization check prevents stale results and
actions from crossing into a replacement session.

## Intentional pairing-code output

The Python clear-text-output finding is **not claimed fixed or dismissed**.
`broker.py --show-code` intentionally returns the full secret to its caller,
including the installer's captured subprocess. Restricting all non-terminal
output would break that contract. Ordinary broker startup logs its listening
address, not the pairing code.

The remaining exposure, safe handling and the existing installer
`--no-show-code` option are documented in `hermes-plugin/README.md`. File
permissions do not protect copies retained in terminal recordings or logs.

The CodeQL gate records this single reviewed intentional output in
`.github/codeql-reviewed.json`. It must match the rule ID, exact source path,
line and entire source file's Git blob checksum. Changing any source bytes
invalidates that review. The result and its true severity stay in the report
and GitHub alert list; no query or SARIF result is filtered or rewritten.
New or changed unreviewed high/critical findings block the gate.

## Verification

`tests/background-security.test.mjs` executes production background, HMAC,
binding and CDP code in a fresh child process for each scenario. Only browser
APIs, WebSocket delivery and selected timer scheduling are simulated. The
matrix covers proof acceptance/rejection/replay, malformed success flags,
optional and invalid keyboard references, revocation during focus/attachment,
wait bounds, queue saturation and reconnect recovery.

`tests/test_pairing_output.py` verifies the explicit stdout contract, real
subprocess capture using temporary credentials, mutually exclusive CLI modes
and normal startup output. `tests/test_codeql_report.py` tests extension/driver
rule resolution, malformed metadata, unknown scores, analysis errors, blocking
exit codes and invalidation of source-bound reviews.

All pre-existing tests and the authenticated packaged-browser snapshot test
remain enabled. CodeQL push runs on `main` and `fix/security-*` branches provide
a full source analysis; pull-request results may be diff-informed. Compare the
full push result, not only a green incremental PR check, before integration.
