"use strict";

(() => {
  if (window.location.hostname !== "edoc.suiyuecare.com") return;

  const params = new URLSearchParams(window.location.search);
  const legacyHandoffKeys = ["payload", "signature", "token", "email", "role", "scope", "portal", "portalLogin"];
  const hasLegacyPortalHandoff = legacyHandoffKeys.some((key) => params.has(key));
  const cookieValue = (name) => {
    const prefix = `${encodeURIComponent(name)}=`;
    const match = document.cookie.split(";").map((item) => item.trim()).find((item) => item.startsWith(prefix));
    return match ? match.slice(prefix.length) : "";
  };
  const returnToPortal = (code) => {
    const loginUrl = new URL("https://login.suiyuecare.com/portal/");
    loginUrl.searchParams.set("returnFrom", "edoc");
    loginUrl.searchParams.set("moduleError", code);
    window.location.replace(loginUrl.toString());
  };

  // Query-string handoffs are intentionally not accepted. They expose a
  // decodable bearer-like payload through history and referrers.
  if (hasLegacyPortalHandoff) {
    returnToPortal("sso_denied");
    return;
  }

  let hasEdocSession = false;
  try {
    hasEdocSession = Boolean(window.localStorage?.getItem("suiyuecare-edoc-session"));
  } catch (error) {
    hasEdocSession = false;
  }
  const hasHandoffMarker = cookieValue("suiyuecare-edoc-handoff-pending") === "1";
  const hasBridgeCookie = Boolean(cookieValue("suiyue_hris_quick_login_user"));
  if (hasHandoffMarker || hasEdocSession || hasBridgeCookie) return;

  // Do not redirect from the head script merely because the JavaScript-readable
  // marker is missing. The real one-time handoff cookie is HttpOnly and may
  // still be present (for example after a browser restores or races a tab).
  // app.js performs one same-origin exchange probe first and only returns to
  // Portal when the backend explicitly reports that no handoff session exists.
  window.__edocProbeHttpOnlyHandoff = true;
})();
