/* Pure, shared seam-group geometry. Positions use unrotated PDF points. */
(function (root) {
  "use strict";
  const ptPerMm = 72 / 25.4;
  const groupId = (element) => element?.kind === "seal" ? element.properties?.seamGroupId || "" : "";
  const rotation = (page) => ((Number(page.rotation || 0) % 360) + 360) % 360;
  const displayHeight = (page) => rotation(page) % 180 ? page.widthPt : page.heightPt;
  function initialTopMm(availableHeightPt, index, count) {
    // Deterministic staggering keeps batch placement reproducible and away from corners.
    const ratio = count > 1 ? 0.2 + 0.6 * index / (count - 1) : 0.5;
    return Math.max(0, availableHeightPt) * ratio / ptPerMm;
  }
  function topPt(page, item) {
    switch (rotation(page)) {
      case 90: return item.x;
      case 180: return item.y;
      case 270: return page.widthPt - item.x - item.width;
      default: return page.heightPt - item.y - item.height;
    }
  }
  function groups(state) {
    const result = new Map();
    for (const element of state.elements || []) {
      const id = groupId(element);
      if (id) result.set(id, [...(result.get(id) || []), element]);
    }
    return result;
  }
  function invalidatedGroups(state) {
    return [...groups(state)].filter(([, members]) => {
      const left = members.find(item => item.properties.seamPartIndex === 0);
      const right = members.find(item => item.properties.seamPartIndex === 1);
      const leftIndex = state.pages.findIndex(page => page.pageId === left?.pageId);
      const rightIndex = state.pages.findIndex(page => page.pageId === right?.pageId);
      return leftIndex < 0 || rightIndex !== leftIndex + 1;
    }).map(([id]) => id);
  }
  function position(state, id, topMm) {
    const members = groups(state).get(id) || [];
    if (members.length !== 2) return false;
    const pages = members.map((item) => state.pages.find((page) => page.pageId === item.pageId));
    if (pages.some((page) => !page)) return false;
    const limit = Math.min(...pages.map((page, index) => displayHeight(page) - members[index].height));
    const top = Math.max(0, Math.min(limit, Number(topMm) * ptPerMm));
    if (!Number.isFinite(top)) return false;
    members.forEach((item, index) => {
      const page = pages[index];
      const r = rotation(page);
      const displayWidth = r % 180 ? page.heightPt : page.widthPt;
      const edge = item.properties.seamPartIndex === 0 ? displayWidth - item.width : 0;
      if (r === 90) { item.x = top; item.y = edge; }
      else if (r === 180) { item.x = page.widthPt - edge - item.width; item.y = top; }
      else if (r === 270) { item.x = page.widthPt - top - item.width; item.y = page.heightPt - edge - item.height; }
      else { item.x = edge; item.y = page.heightPt - top - item.height; }
      item.x = Math.round(item.x * 10000) / 10000;
      item.y = Math.round(item.y * 10000) / 10000;
      item.rotation = 0;
    });
    return true;
  }
  function reconcile(state, previous) {
    const old = new Map((previous.elements || []).map((item) => [item.id, item]));
    const invalid = new Set(invalidatedGroups(state));
    for (const [id, members] of groups(state)) {
      if (members.length !== 2 || invalid.has(id) || members.some((item) => !state.pages.some((page) => page.pageId === item.pageId))) {
        state.elements = state.elements.filter((item) => groupId(item) !== id);
        continue;
      }
      const changed = members.find((item) => old.has(item.id) && (item.y !== old.get(item.id).y || item.x !== old.get(item.id).x)) || members[0];
      const page = state.pages.find((item) => item.pageId === changed.pageId);
      const oldPage = (previous.pages || []).find((entry) => entry.pageId === page.pageId);
      const oldItem = old.get(changed.id);
      const top = oldPage && oldItem && rotation(oldPage) !== rotation(page) ? topPt(oldPage, oldItem) : topPt(page, changed);
      position(state, id, top / ptPerMm);
      const styled = members.find((item) => old.has(item.id) && item.opacity !== old.get(item.id).opacity) || members[0];
      members.forEach((item) => { item.opacity = styled.opacity; item.rotation = 0; });
    }
  }
  root.EDOCSeam = { groups, groupId, position, reconcile, invalidatedGroups, ptPerMm, topPt, displayHeight, initialTopMm };
  if (typeof module !== "undefined") module.exports = root.EDOCSeam;
})(typeof globalThis !== "undefined" ? globalThis : window);
