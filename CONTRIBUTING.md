# Contributing

Open a focused pull request against `main`. Explain the observed problem,
expected behavior, scope of the change, and the tests performed. Security
reports belong in the private channel described in [SECURITY.md](SECURITY.md).

## Local checks

Use Node.js 22 and Python 3.12 in a disposable virtual environment. Install the
test dependency and run the same fast gate used in CI:

```sh
python -m pip install websockets==15.0.1
python tests/run_all.py
```

The runner discovers all `tests/test_*.py` and `tests/*.test.mjs` files. It also
checks JavaScript syntax, release metadata, sensitive-data patterns, and line
endings. A focused dashboard-navigation check is available with:

```sh
node --test tests/sidepanel-navigation.test.mjs
```

For a bug fix, add a behavioral regression test that fails without the fix.
Do not merely assert that a particular source string exists. Test relevant
failure paths, asynchronous ordering, and session/profile isolation. Test
fixtures must not contact production services or use real pairing credentials.

## CI and review

The release gate runs on Windows, Ubuntu, and macOS. Platform installer tests
run in isolated fixtures; Linux additionally builds release archives and runs
packaged Chrome acceptance. CodeQL checks JavaScript and Python separately.
Inspect skipped steps and reported findings as well as the overall result.

Before merging, check the latest PR head rather than an earlier successful
commit. Preserve contributor attribution and avoid unrelated formatting or
refactoring in a corrective change. Review first-time contributor changes
before permitting their workflows to run.

Actions are pinned to full commit SHAs. Dependabot proposes their updates;
review those changes and rerun CI before merging. Runtime and installer
dependency pins still need a separate compatibility review.

## Publishing

Merging a fix is not publishing a new extension. Follow
[PUBLISHING.md](PUBLISHING.md), update the matching extension/companion release
contract, and validate the exact distributable archives. Never overwrite an
existing release's assets with a different build under the same version.

## Repository administration

`CODEOWNERS`, workflow files, and documentation do not themselves protect
`main`. An administrator must activate an appropriate repository ruleset to
require pull requests and successful checks and to block forced updates and
branch deletion. For a solo maintainer, mandatory checks can be enabled without
requiring a second human approval. Avoid routine bypass permissions.
