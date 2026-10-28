"use strict";
window.PULSE_SAMPLE = true;
const snapshot = fetch("sample-data.json").then((response) => {
  if (!response.ok)
    throw new Error(
      "Sample could not load. Reload or download the sample Markdown.",
    );
  return response.json();
});
window.pulseDemoGet = async function (path) {
  const data = await snapshot;
  const url = new URL(path, location.origin);
  if (url.pathname === "/api/review") return data.review;
  if (url.pathname === "/api/items") return data.items;
  if (url.pathname === "/api/workstreams") return data.workstreams;
  if (url.pathname === "/api/briefing") return data.briefing;
  if (url.pathname === "/api/evidence")
    return {
      events: data.events.filter((event) =>
        url.searchParams.getAll("id").includes(event.id),
      ),
    };
  if (url.pathname === "/api/workstream") {
    const id = url.searchParams.get("id");
    return {
      workstream: data.workstreams.workstreams.find(
        (workstream) => workstream.id === id,
      ),
      items: data.items.items.filter((item) => item.workstream_id === id),
      events: data.events.filter((event) => event.workstream_id === id),
    };
  }
  throw new Error(
    "This feature needs the local app. The public workspace only uses synthetic records.",
  );
};
