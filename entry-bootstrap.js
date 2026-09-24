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
  const portalUrl = "https://login.suiyuecare.com/portal/";
  const returnToPortal = (code) => {
    const loginUrl = new URL(portalUrl);
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

  const readCachedEdocSession = () => {
    try {
      const rawSession = window.localStorage?.getItem("suiyuecare-edoc-session") || "";
      const session = rawSession ? JSON.parse(rawSession) : null;
      return session?.user && typeof session.token === "string" && /^[\x21-\x7e]+$/.test(session.token) ? session : null;
    } catch (error) {
      return null;
    }
  };
  const cachedEdocSession = readCachedEdocSession();
  const hasEdocSession = Boolean(cachedEdocSession);

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

  // Legacy bridges still belong to app.js; this probe is only for a fresh
  // entry with no client-side session or bridge to resume.
  const bridgeStorageKeys = ["suiyue-hris-quick-login-user", "suiyuecare-logging-session", "suiyue-logging-session", "suiyue-platform-session"];
  const hasLegacyClientBridge = () => {
    // Match readJsonStorage: storage is plain JSON, not URI-decoded JSON.
    if (bridgeStorageKeys.some((key) => {
      try {
        const value = JSON.parse(window.localStorage?.getItem(key) || "null");
        return Boolean(value?.user || value?.email || value?.session || value?.profile || value?.currentUser);
      } catch (error) {
        return false;
      }
    })) return true;
    const prefix = "suiyue_hris_quick_login_user:";
    if (!window.name?.startsWith(prefix)) return false;
    const raw = window.name.slice(prefix.length);
    // Match parseJsonMaybe for window.name, including its URI-encoded form.
    try {
      return Boolean(JSON.parse(raw));
    } catch (error) {
      try {
        return Boolean(JSON.parse(decodeURIComponent(raw)));
      } catch (decodeError) {
        return false;
      }
    }
  };
  if (hasLegacyClientBridge()) return;

  // Do not redirect from the head script merely because the JavaScript-readable
  // marker is missing. The real one-time handoff cookie is HttpOnly and may
  // still be present (for example after a browser restores or races a tab).
  // Start that same-origin exchange before the main bundle is downloaded.
  // app.js consumes this exact Response once, with its normal parser/retries.
  window.__edocProbeHttpOnlyHandoff = true;
  if (window.__edocEarlyHandoffResponse) return;
  const responsePromise = Promise.resolve().then(() => fetch("/api/auth/handoff-session", {
    method: "POST",
    credentials: "same-origin",
    cache: "no-store",
    headers: { "Content-Type": "application/json", "X-EDOC-Handoff-Exchange": "1" },
    ...(typeof AbortSignal !== "undefined" && typeof AbortSignal.timeout === "function" ? { signal: AbortSignal.timeout(6000) } : {}),
    body: "{}"
  }));
  window.__edocEarlyHandoffResponse = responsePromise;
  responsePromise.then(async (response) => {
    if (response.status !== 401) return;
    const data = await response.clone().json();
    if (data?.error !== "handoff_session_missing" || window.__edocEarlyHandoffResponse !== responsePromise) return;
    // Another tab may finish signing in while this request is in flight.
    if (readCachedEdocSession() || hasLegacyClientBridge()
      || cookieValue("suiyuecare-edoc-handoff-pending") === "1" || cookieValue("suiyue_hris_quick_login_user")) return;
    // Keep this target identical to buildLoggingPortalUrl(): only a backend-
    // confirmed missing session may return to Portal before app.js takes over.
    const returnUrl = new URL(window.location.href);
    ["payload", "signature", "token", "email", "role", "scope", "portal"].forEach((key) => returnUrl.searchParams.delete(key));
    returnUrl.searchParams.delete("localLogin");
    const resumableRoutes = new Set(["dashboard", "compose", "electronicSeal", "approvalLog", "inbound", "settings"]);
    const requestedRoute = returnUrl.hash.replace(/^#/, "");
    returnUrl.hash = resumableRoutes.has(requestedRoute) ? requestedRoute : "";
    const loginUrl = new URL(portalUrl);
    loginUrl.searchParams.set("module", "edoc");
    loginUrl.searchParams.set("next", returnUrl.toString());
    window.location.replace(loginUrl.toString());
  }).catch(() => {
    // This observer never consumes or replaces the original Response promise.
    // Network/JSON errors and temporary outages remain app.js responsibilities.
  });
})();
