/* Pure, shared seam-group geometry. Positions use unrotated PDF points. */
(function (root) {
  "use strict";
  const ptPerMm = 72 / 25.4;
  const CURRENT_POLICY = "right-edge-10mm-v2";
  const MARGIN_PT = 10 * ptPerMm;
  const isCurrentPolicy = (item) => item?.properties?.seamPolicyVersion === CURRENT_POLICY;
  const groupId = (element) => element?.kind === "seal" ? element.properties?.seamGroupId || "" : "";
  const mode = (element) => element?.properties?.seamMode || "pair";
  const edge = (element) => mode(element) === "grouped" ? element.properties?.seamEdge || "right" : "pair";
  const partCount = (element) => mode(element) === "grouped" ? Number(element.properties?.seamPartCount) : 2;
  const rotation = (page) => ((Number(page.rotation || 0) % 360) + 360) % 360;
  const displayHeight = (page) => rotation(page) % 180 ? page.widthPt : page.heightPt;
  const displayWidth = (page) => rotation(page) % 180 ? page.heightPt : page.widthPt;
  const displaySize = (page, item) => rotation(page) % 180 ? { width: item.height, height: item.width } : { width: item.width, height: item.height };
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
  function leftPt(page, item) {
    switch (rotation(page)) {
      case 90: return item.y;
      case 180: return page.widthPt - item.x - item.width;
      case 270: return page.heightPt - item.y - item.height;
      default: return item.x;
    }
  }
  function offsetPt(page, item) {
    return ["top", "bottom"].includes(edge(item)) ? leftPt(page, item) : topPt(page, item);
  }
  function partitionPages(numbers, maxCount = 5) {
    if (!Number.isInteger(maxCount) || maxCount < 1 || maxCount > 5) return [];
    const values = [...new Set(numbers)].sort((a, b) => a - b);
    if (values.some((value) => !Number.isInteger(value) || value < 1)) return [];
    const result = [];
    for (const number of values) {
      const last = result[result.length - 1];
      if (!last || last.length === maxCount || number !== last[last.length - 1] + 1) result.push([number]);
      else last.push(number);
    }
    return result;
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
      const count = partCount(members[0]);
      const groupMode = mode(members[0]);
      const groupEdge = edge(members[0]);
      const policy = members[0].properties?.seamPolicyVersion || "";
      const ordered = [...members].sort((a, b) => Number(a.properties.seamPartIndex) - Number(b.properties.seamPartIndex));
      if (!Number.isInteger(count) || count < 1 || count > 5 || members.length !== count
        || !["pair", "grouped"].includes(groupMode)
        || (groupMode === "pair" && count !== 2)
        || (groupMode === "grouped" && !["left", "right", "top", "bottom"].includes(groupEdge))
        || (policy && policy !== CURRENT_POLICY)
        || (policy === CURRENT_POLICY && (groupMode !== "grouped" || groupEdge !== "right"))) return true;
      const indexes = ordered.map(item => state.pages.findIndex(page => page.pageId === item.pageId));
      return indexes[0] < 0 || ordered.some((item, index) => item.properties.seamPartIndex !== index
        || mode(item) !== groupMode || partCount(item) !== count || edge(item) !== groupEdge
        || (item.properties?.seamPolicyVersion || "") !== policy
        || indexes[index] !== indexes[0] + index);
    }).map(([id]) => id);
  }
  function offsetLimitPt(state, id, requestedEdge = null) {
    const members = groups(state).get(id) || [];
    if (!members.length) return 0;
    const selectedEdge = requestedEdge || edge(members[0]);
    const pages = members.map((item) => state.pages.find((page) => page.pageId === item.pageId));
    if (pages.some((page) => !page)) return 0;
    return Math.max(0, Math.min(...pages.map((page, index) => {
      const size = displaySize(page, members[index]);
      return ["top", "bottom"].includes(selectedEdge) ? displayWidth(page) - size.width : displayHeight(page) - size.height;
    })));
  }
  function offsetBoundsPt(state, id, requestedEdge = null) {
    const members = groups(state).get(id) || [];
    const margin = members.length && isCurrentPolicy(members[0]) ? MARGIN_PT : 0;
    return { min: margin, max: offsetLimitPt(state, id, requestedEdge) - margin };
  }
  function initialBatchTopMm(state, ids) {
    const bounds = ids.map((id) => offsetBoundsPt(state, id, "right"));
    if (!bounds.length) return 0;
    const min = Math.max(...bounds.map((item) => item.min));
    const max = Math.min(...bounds.map((item) => item.max));
    return max < min ? NaN : (min + max) / 2 / ptPerMm;
  }
  function position(state, id, offsetMm, requestedEdge = null) {
    const members = groups(state).get(id) || [];
    if (!members.length || members.length !== partCount(members[0])) return false;
    const pages = members.map((item) => state.pages.find((page) => page.pageId === item.pageId));
    if (pages.some((page) => !page)) return false;
    const selectedEdge = mode(members[0]) === "grouped" ? requestedEdge || edge(members[0]) : "pair";
    if (!["pair", "left", "right", "top", "bottom"].includes(selectedEdge)) return false;
    if (members.some((item) => (item.properties?.seamPolicyVersion || "") !== (members[0].properties?.seamPolicyVersion || ""))
      || (members[0].properties?.seamPolicyVersion && !isCurrentPolicy(members[0]))
      || (isCurrentPolicy(members[0]) && (mode(members[0]) !== "grouped" || selectedEdge !== "right"))) return false;
    const bounds = offsetBoundsPt(state, id, selectedEdge);
    if (bounds.max < bounds.min) return false;
    const offset = Math.max(bounds.min, Math.min(bounds.max, Number(offsetMm) * ptPerMm));
    if (!Number.isFinite(offset)) return false;
    members.forEach((item, index) => {
      const page = pages[index];
      const r = rotation(page);
      const size = displaySize(page, item);
      const memberEdge = selectedEdge === "pair" ? item.properties.seamPartIndex === 0 ? "right" : "left" : selectedEdge;
      const left = memberEdge === "left" ? 0 : memberEdge === "right" ? displayWidth(page) - size.width : offset;
      const top = memberEdge === "top" ? 0 : memberEdge === "bottom" ? displayHeight(page) - size.height : offset;
      if (r === 90) { item.x = top; item.y = left; }
      else if (r === 180) { item.x = page.widthPt - left - item.width; item.y = top; }
      else if (r === 270) { item.x = page.widthPt - top - item.width; item.y = page.heightPt - left - item.height; }
      else { item.x = left; item.y = page.heightPt - top - item.height; }
      item.x = Math.round(item.x * 10000) / 10000;
      item.y = Math.round(item.y * 10000) / 10000;
      item.rotation = 0;
      if (mode(item) === "grouped") item.properties.seamEdge = selectedEdge;
    });
    return true;
  }
  function previewSlice(item, width, height, pageRotation = 0) {
    const count = partCount(item), index = Number(item.properties?.seamPartIndex), selectedEdge = edge(item);
    const horizontal = ["top", "bottom"].includes(selectedEdge);
    const total = horizontal ? height : width;
    const start = total * index / count, length = total / count;
    const target = selectedEdge === "right" || selectedEdge === "bottom" || (selectedEdge === "pair" && index === 0) ? total - length : 0;
    const slice = horizontal
      ? { clip: { x: 0, y: target, width, height: length }, image: { x: 0, y: target - start, width, height } }
      : { clip: { x: target, y: 0, width: length, height }, image: { x: target - start, y: 0, width, height } };
    if (mode(item) !== "grouped") return slice;
    const r = ((Number(pageRotation) % 360) + 360) % 360;
    const shiftX = horizontal ? 0 : target - start, shiftY = horizontal ? target - start : 0;
    // Apply PDF viewport quarter-turns to the original image, not its aspect
    // ratio. The clip stays in displayed-page coordinates at the chosen edge.
    const matrix = r === 90 ? [0, 1, -1, 0, width + shiftX, shiftY]
      : r === 180 ? [-1, 0, 0, -1, width + shiftX, height + shiftY]
      : r === 270 ? [0, -1, 1, 0, shiftX, height + shiftY]
      : [1, 0, 0, 1, shiftX, shiftY];
    slice.image = { x: 0, y: 0, width: r % 180 ? height : width, height: r % 180 ? width : height,
      transform: `matrix(${matrix.join(" ")})` };
    return slice;
  }
  function reconcile(state, previous) {
    const old = new Map((previous.elements || []).map((item) => [item.id, item]));
    const invalid = new Set(invalidatedGroups(state));
    for (const [id, members] of groups(state)) {
      if (invalid.has(id) || members.some((item) => !state.pages.some((page) => page.pageId === item.pageId))) {
        state.elements = state.elements.filter((item) => groupId(item) !== id);
        continue;
      }
      const changed = members.find((item) => old.has(item.id) && (item.y !== old.get(item.id).y || item.x !== old.get(item.id).x)) || members[0];
      const page = state.pages.find((item) => item.pageId === changed.pageId);
      const oldPage = (previous.pages || []).find((entry) => entry.pageId === page.pageId);
      const oldItem = old.get(changed.id);
      const offset = oldPage && oldItem && rotation(oldPage) !== rotation(page) ? offsetPt(oldPage, oldItem) : offsetPt(page, changed);
      position(state, id, offset / ptPerMm);
      const styled = members.find((item) => old.has(item.id) && item.opacity !== old.get(item.id).opacity) || members[0];
      members.forEach((item) => { item.opacity = styled.opacity; item.rotation = 0; });
    }
  }
  root.EDOCSeam = { groups, groupId, mode, edge, partCount, position, reconcile, invalidatedGroups, ptPerMm, topPt, leftPt, offsetPt, offsetLimitPt, offsetBoundsPt, initialBatchTopMm, CURRENT_POLICY, MARGIN_PT, isCurrentPolicy, displayHeight, displayWidth, initialTopMm, partitionPages, previewSlice };
  if (typeof module !== "undefined") module.exports = root.EDOCSeam;
})(typeof globalThis !== "undefined" ? globalThis : window);
