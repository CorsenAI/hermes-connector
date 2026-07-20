# Release acceptance gates

The project is not "done" until every applicable gate below has evidence from
the final packaged bits.

## Routing

- [x] Two Hermes sessions attached to two different tabs act only in their own
      tabs under interleaved requests.
- [x] One Hermes session can list, open, switch between, and close multiple
      attached tabs without seeing another session's tabs.
- [x] Two connected Chrome profiles have stable distinct browser identities and
      can be selected deterministically.
- [x] An unbound session receives a clear error and never acts in the currently
      focused or most-recent tab.
- [x] Closing, detaching, or transferring a target invalidates the former
      binding before the next action.

## Hermes integration

- [ ] The panel displays the running real Hermes dashboard and resumes the
      selected real session in the user's intended Google Chrome profile.
- [x] The tool handler routes the real `PluginContext.profile_name` and the real
      tool-call `session_id`; no hard-coded test profile participates.
- [x] Multiple Hermes profile clients can use the companion concurrently while
      only one local broker owns port 8765.
- [ ] Restarting the dashboard, gateway, broker, extension worker, and Chrome
      has documented and verified recovery behaviour in the final profile.

## Browser actions

- [x] Navigation, snapshot, reading, click, type, scroll, screenshot, hover,
      keyboard, select, drag, find, history, and tab actions pass against real
      pages with honest failures.
- [x] Trusted input is exercised live, including a cancelled confirm dialog and
      debugger detach.
- [x] Restricted pages and unsupported schemes fail safely.

## Distribution and Store

- [x] Clean companion installation succeeds on Windows, macOS, and Linux, or
      unsupported platforms are removed from the listing.
- [x] Isolated companion installation and the full fast gate pass on Windows
      and Ubuntu Linux; the release ZIP preserves POSIX executable mode.
- [x] The final extension ZIP contains only allowlisted runtime files and
      matches committed/tagged source through a recorded SHA-256 hash.
- [x] Automated leakage checks find no personal data, secrets, local paths, test
      identities, or authorship markers in distributed files.
- [x] Store icon, 440×280 promotional tile, and actual-product 1280×800
      screenshot pass exact PNG-dimension gates and use isolated test data.
- [ ] Store permissions, data-use declarations, privacy policy, screenshots,
      hosted URLs, and installation instructions match the tested product.
- [x] End-to-end runs are completed in one and two isolated Chrome profiles.
- [ ] A final end-to-end run is completed in the user's intended signed-in
      Google Chrome profile.

Evidence for checked gates is recorded in `TEST-EVIDENCE.md`.
