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

## Full-analysis dispositions

The full push analysis of commit `044fc4ef29f14874c77709fe1a8774f215ee14ee`
(run `35037307711`, CodeQL CLI 2.27.0, security-extended) reports four
JavaScript results and one Python result. The snapshot escaping result is
absent. This is not a zero-alert repository: the new strict `ok !== true`
check adds one generic bypass result. No query has been disabled.

The complete SARIF paths were reviewed, not just their titles:

| Location in background.js | Rule | Disposition and evidence |
| --- | --- | --- |
| 538 | user-controlled-bypass | The incoming proof is compared with a locally calculated HMAC before authority is established. Wrong, absent, unsolicited and replayed proofs are rejected by the production state machine in tests. |
| 550 | user-controlled-bypass | A literal success flag is required in addition to the already verified HMAC. Invalid flag types cannot establish authority. This additional generic finding is acknowledged, not hidden. |
| 1050 | user-controlled-bypass | The branch controls optional focus, not whether keyboard authorization runs. Production CDP authorization still executes without a ref; revocation tests confirm zero keyboard events after focus/attachment revocation. |
| 1023 | resource-exhaustion | The data path reaches a finite, explicitly bounded delay (0..15000). The queue and timer tests verify saturation rejection, one active timer and recovery after reconnect. |

These four JavaScript paths are classified as false positives for the tested
security properties. This is a scoped engineering disposition, not a claim
that the whole extension is vulnerability-free. The Python secret-output
finding remains a documented intentional exposure, not a false positive about
the fact that a secret is displayed.

The gate uses `.github/codeql-reviewed.json` to record these exact results.
Every entry must match the rule ID, severity, exact source path, single line and
whole-file Git blob checksum. Relevant imported source and regression tests
are also pinned as dependencies. Changing them invalidates the disposition;
it cannot silently follow an altered control. All results and their true
severity stay in SARIF and GitHub. Only these reviewed results are nonblocking;
new, moved, changed or unreviewed high/critical findings still block.

The original failing full analysis is retained as a workflow artifact, together
with the verifier output. Subsequent full push analysis must still account for
these results. A green gate means the documented dispositions matched the
reviewed sources, not that the scanner emitted no findings.

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
