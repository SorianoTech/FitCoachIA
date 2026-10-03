# FitCoach Telegram Mini App

Includes the administrator quota panel. Visibility is discovered through the signed
`/api/miniapp/admin/access` endpoint; the server independently authorizes every admin
request. Administrators can open the panel without a training plan. Configure
`miniapp_admin_chat_ids` on the API; permissions cannot be granted by the frontend.

Mobile-first React + TypeScript frontend. Node.js 22+ recommended.

```sh
cd frontend
npm ci
npm test
npm run build
```

The build type-checks the app and writes `dist/`, with asset URLs under `/miniapp/`.
The parent application must serve these assets at `/miniapp/` and provide the
same-origin `/api/miniapp/*` API. `npm run dev` starts Vite for frontend development;
it does not emulate authentication or provide an API proxy.

Configure the bot's Mini App URL to the deployed HTTPS `/miniapp/` URL. The official
Telegram WebApp SDK is loaded in `index.html`; every API call sends its `initData`
in `X-Telegram-Init-Data`. Opening outside Telegram produces an explicit error.
There is no development authentication bypass.

Drafts, request UUIDs and timer state live only in memory: no browser storage or
service worker stores health records or credentials. Marking a set done saves a
full snapshot; explicit save also supports partial sessions. Writes are serialized,
conflicts require an explicit reload, and completed sessions are read-only.
Dirty drafts trigger Telegram closing confirmation and browser unload warnings
(platform support varies); deliberately discarding, closing or refreshing can
lose unsaved edits. Rest timers use wall-clock deadlines and do not promise
notifications or execution in the background.

Swaps and cycle reviews hand off to the bot for its existing proposal/approval
workflow. Calendar dates never automatically complete or review a cycle.
History and per-exercise progress describe recent sessions, with progress exposing
the API's `history_limit` and `history_truncated` metadata. The completed-session
counter is explicitly labeled as a lifetime total, not a count of visible rows.
Duration-only work shows recorded seconds and a dash for unknown repetitions;
missing measurements are never inferred as zero.
