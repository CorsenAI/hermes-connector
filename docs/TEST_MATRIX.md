# TEST_MATRIX — Hermes Connector 0.2.5

> One case per line. Nothing is DONE without (a) an automatic test and (b) a manual check in a
> real Chrome. "Proof" names the exact test or evidence file.

| ID | Case | Type | Command / gesture | Expected | Status | Proof | Date |
|---|---|---|---|---|---|---|---|
| T-101 | Broker relays `browser_query list_sessions` to a connected companion and returns its answer | auto | `python -m unittest tests.test_broker -k query` | `browser_query_result ok:true` with the companion payload | TODO | | |
| T-102 | No companion connected → bounded error, no hang | auto | same | `ok:false`, error names "no Hermes" | TODO | | |
| T-103 | Companion never answers → timeout error, pending entry cleaned | auto | same | error within the relay timeout; `pending` empty | TODO | | |
| T-104 | Oversized / malformed query or result is rejected | auto | same | frame dropped or error, socket stays usable | TODO | | |
| T-105 | A browser that is not authenticated gets no relay | auto | same | socket closed at hello, nothing routed | TODO | | |
| T-106 | Companion provider projection keeps only allowed fields, caps rows and title length | auto | `python -m unittest tests.test_plugin_sessions` | no `cwd`/cost/token keys; ≤200 rows; title ≤200 chars | TODO | | |
| T-107 | Companion answers `agent_query` from a fake provider; provider exception → `ok:false` | auto | same | exact `agent_query_result` frames | TODO | | |
| T-108 | Pure session-source order: dashboard → companion → headless | auto | `node --test tests/session-sources.test.mjs` | first available source wins; mode labels correct | TODO | | |
| T-109 | Background answers `listSessions` from the panel through the paired socket | auto | `node --test tests/background-session.test.mjs` | resolves with sessions; rejects when unpaired | TODO | | |
| T-110 | Panel: dashboard down + no headless backend + companion present → list filled, status "Chrome linked · choose a session", conversation-in-Hermes notice | auto (Chromium) | `python tests/e2e_chromium.py` | new scenario green, existing scenarios green | TODO | | |
| T-111 | Panel: nothing answers → wording names what to start | auto (Chromium) | same | status text per R5 | TODO | | |
| T-112 | Release gate | auto | `python tests/run_all.py` | "Fast release gate passed." with 0.2.5 everywhere | TODO | | |
| T-113 | Packaged release archives | auto | `python scripts/build_release.py` | two zips + release JSON, leakage scan clean | TODO | | |
| T-114 | Real Hermes acceptance on a temporary home (model turn + session list through the companion, dashboard absent) | manual/opt-in | `python tests/e2e_real_hermes.py` | `bridge_*` called by the model; panel lists the temp session | TODO | | |
| T-115 | Manual check on the owner's Chrome (unpacked 0.2.5 + 0.2.5 companion on an isolated home) | manual | load unpacked, ↻ | screenshot of the filled list without a dashboard | TODO | | |

Statuses: `TODO` · `IN PROGRESS` · `PASS` · `FAIL` · `BLOCKED` · `N/A` (with reason).
