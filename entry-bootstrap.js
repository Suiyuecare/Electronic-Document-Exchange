"use strict";

(() => {
  if (window.location.hostname !== "edoc.suiyuecare.com") return;

  const cachedShellRevealTargetMs = 500;

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
  let cachedEdocSession = null;
  try {
    const rawSession = window.localStorage?.getItem("suiyuecare-edoc-session") || "";
    cachedEdocSession = rawSession ? JSON.parse(rawSession) : null;
    hasEdocSession = Boolean(
      cachedEdocSession?.user
      && typeof cachedEdocSession.token === "string"
      && /^[\x21-\x7e]+$/.test(cachedEdocSession.token)
    );
  } catch (error) {
    hasEdocSession = false;
    cachedEdocSession = null;
  }

  if (hasEdocSession) {
    const revealCachedShell = () => {
      const appShell = document.querySelector("#appShell");
      const loginScreen = document.querySelector("#loginScreen");
      const entryScreen = document.querySelector("#moduleEntryProgress");
      const roleLabel = document.querySelector("#currentRoleLabel");
      const roleNote = document.querySelector("#roleNote");
      const avatar = document.querySelector("#currentUserAvatar");
      const topInfo = document.querySelector("#topInfo");
      if (!document.body || !appShell || !roleLabel || !roleNote || !topInfo) return false;

      const user = cachedEdocSession.user || {};
      const displayName = String(user.name || user.email || "公司帳號").trim();
      const role = String(user.role || "身份確認中").trim();
      document.body.dataset.sessionState = "revalidating";
      appShell.classList.remove("hidden");
      appShell.setAttribute("inert", "");
      appShell.setAttribute("aria-busy", "true");
      loginScreen?.classList.add("hidden");
      loginScreen?.setAttribute("aria-hidden", "true");
      entryScreen?.classList.add("hidden");
      roleLabel.textContent = `${displayName} · ${role}`;
      roleNote.textContent = `${user.company_name || "公司確認中"} · ${user.unit || "部門確認中"} · 正在同步最新權限`;
      if (avatar) avatar.textContent = Array.from(displayName)[0] || "帳";
      topInfo.textContent = `${displayName} · ${role} · 正在同步`;
      window.__edocCachedShellTargetMs = cachedShellRevealTargetMs;
      window.__edocCachedShellRevealedAt = window.performance?.now?.() || Date.now();
      return true;
    };

    if (!revealCachedShell()) {
      const observer = new MutationObserver(() => {
        if (!revealCachedShell()) return;
        observer.disconnect();
      });
      observer.observe(document.documentElement, { childList: true, subtree: true });
    }
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
