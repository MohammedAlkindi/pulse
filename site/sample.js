"use strict";
fetch("sample.md").then((response) => {
  if (!response.ok) throw new Error("Sample unavailable");
  return response.text();
}).then((markdown) => {
  document.getElementById("sample").innerHTML = renderBriefing(markdown);
}).catch(() => {
  document.getElementById("sample").textContent = "The sample could not load. Download the Markdown below or try again.";
});
