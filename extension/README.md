# LinkBypassor extension (option 3)

One-time install, then **paste → Bypass → magic**. No Tampermonkey, no
`javascript:` pasting, no DevTools.

## Install (developer mode, 1 min)

**Chrome / Edge / Brave:**
1. Open `chrome://extensions` → enable **Developer mode** (top right).
2. **Load unpacked** → select this `extension/` folder.
3. Pin LinkBypassor to the toolbar. Done.

**Firefox:**
1. Open `about:debugging#/runtime/this-firefox` → **Load Temporary Add-on**.
2. Select any file inside `extension/` (e.g. `manifest.json`).
3. Note: temporary add-ons unload on browser restart; for permanent install
   the extension needs signing via addons.mozilla.org (free).

## Use

Click the toolbar icon → paste short link → **Bypass**. The link opens in a
new tab where the content script walks the 4 steps + interstitial on your own
residential IP (~1 min). The popup polls History and shows Copy/Open when the
result lands. Full history lives on the site.

## Files

- `manifest.json` — MV3, content-script matches + host permissions
- `content.js` — the bypass engine (ported from `bypass.user.js`)
- `popup.html` / `popup.js` — paste-link popup with result polling
- `icons/` — toolbar icons
