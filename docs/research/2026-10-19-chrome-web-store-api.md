# Chrome Web Store API — publishing without the dashboard UI (verified 2026-10-19)

Why this matters: the agent cannot drive the Developer Dashboard. Chrome forbids extensions
(including Hermes Connector) on Chrome Web Store pages, and Google rejects sign-in from automated
browsers. The documented alternative is the Chrome Web Store API.

## Facts (official documentation)

- The Chrome Web Store API (V2, the current version since October 2025) creates, updates and
  publishes items: `media.upload`, `publishers.items.publish`, `fetchStatus`,
  `cancelSubmission`, `setPublishedDeployPercentage`.
  Source: <https://developer.chrome.com/docs/webstore/api> (fetched 2026-10-19).
- Setup: enable "Chrome Web Store API" in a Google Cloud project, then either an OAuth consent
  screen + client (refresh token) or a **service account**. The publisher ID is shown in the
  Developer Dashboard under Publisher > Settings. 2-step verification is required on the Google
  account to publish. Source: <https://developer.chrome.com/docs/webstore/using-api>
  (page last updated 2026-10-08).
- Service accounts are supported: create it in Google Cloud (no extra IAM role needed), then add
  its e-mail in the Developer Dashboard, **Account** section — only one service account per
  publisher. Tokens come from service-account impersonation (`gcloud`, needs
  `roles/iam.serviceAccountTokenCreator`, which project owners have) or other standard flows.
  Source: <https://developer.chrome.com/docs/webstore/service-accounts> (fetched 2026-10-19).
- If dashboard settings (e.g. visibility) were changed manually, the API cannot publish until one
  manual publication with the new settings has happened. Source: using-api page above.

## Consequence for this project

The owner's one-time steps would be: Google Cloud project + API enabled + service account (can be
driven in his attached Chrome tab), and adding the service-account e-mail in the Developer
Dashboard Account section (his hands only). After that the agent can upload and submit new
versions itself. Not set up yet — owner decision pending.
