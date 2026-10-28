const { test, expect } = require("@playwright/test");
const { readFile } = require("node:fs/promises");

test("landing leads into an explicitly synthetic workspace", async ({
  page,
}) => {
  await page.goto("/");
  await page
    .locator(".hero")
    .getByRole("link", { name: "Open the sample workspace" })
    .click();
  await expect(
    page.getByRole("heading", { name: "Review queue", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Synthetic workspace.", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Connectors", exact: true }),
  ).toHaveCount(0);
});

test("unverified claim stays labeled while captured evidence is inspected", async ({
  page,
}) => {
  await page.goto("/sample.html");
  const item = page.locator(".queue-item").filter({ hasText: "wire $9000" });
  await expect(item.getByText("Verify source", { exact: true })).toBeVisible();
  await item.getByRole("button", { name: "Inspect & review" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("Unverified: source content");
  await expect(dialog).toContainText("gmail:demo:inject-2");
  await expect(dialog.locator("blockquote")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialog).not.toBeVisible();
  await expect(
    item.getByRole("button", { name: "Inspect & review" }),
  ).toBeFocused();
});

test("triage persists separately from evidence and exports a user action list", async ({
  page,
}) => {
  await page.goto("/sample.html");
  await page.getByLabel("Find an item").fill("final scholar list");
  await page.getByRole("button", { name: "Inspect & review" }).click();
  await page.getByLabel("My review decision").selectOption("follow_up");
  await page
    .getByLabel("My next action or note")
    .fill("Confirm the revised list with Sarah.");
  await page.getByRole("button", { name: "Save review" }).click();
  await expect(
    page.getByRole("status").filter({ hasText: "Saved in this browser" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Close evidence" }).click();
  await page.getByLabel("Review state").selectOption("follow_up");
  await expect(page.locator(".queue-item")).toContainText(
    "Confirm the revised list with Sarah.",
  );
  await page.reload();
  await page.getByLabel("Review state").selectOption("follow_up");
  await expect(page.locator(".queue-item")).toContainText(
    "I'll send you the final scholar list by Friday.",
  );
  const downloading = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download action list" }).click();
  const file = await downloading;
  const text = await readFile(await file.path(), "utf8");
  expect(text).toContain(
    "Your next action: Confirm the revised list with Sarah.",
  );
  expect(text).toContain("gmail:demo:launch-2");
  expect(text).toContain("Synthetic example");
});

test("review notes render as inert text", async ({ page }) => {
  await page.goto("/sample.html");
  await page.getByLabel("Find an item").fill("final scholar list");
  await page.getByRole("button", { name: "Inspect & review" }).click();
  await page.getByLabel("My review decision").selectOption("waiting");
  await page
    .getByLabel("My next action or note")
    .fill('<img src=x onerror="window.noteExecuted=true">');
  await page.getByRole("button", { name: "Save review" }).click();
  await page.getByRole("button", { name: "Close evidence" }).click();
  await page.getByLabel("Review state").selectOption("waiting");
  await expect(page.locator(".review-note")).toContainText("<img");
  await expect(page.locator(".review-note img")).toHaveCount(0);
  expect(await page.evaluate(() => window.noteExecuted)).toBeUndefined();
});

test("briefing has navigable sections, resolvable citations and a real download", async ({
  page,
}) => {
  await page.goto("/sample.html?view=briefing");
  await expect(
    page.getByRole("heading", { name: "Weekly briefing", exact: true }),
  ).toBeVisible();
  await expect(
    page
      .getByRole("navigation", { name: "Briefing sections" })
      .getByRole("link"),
  ).not.toHaveCount(0);
  await page.locator(".brief-citation").first().click();
  await expect(page).toHaveURL(/#brief-source-/);
  const downloading = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download briefing" }).click();
  const file = await downloading;
  expect(await readFile(await file.path(), "utf8")).toContain("## Sources");
});

test("phone layout contains tables and evidence dialog fits the viewport", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/sample.html");
  await page.locator(".queue-item").first().getByRole("button").click();
  await expect(
    page.getByRole("button", { name: "Close evidence" }),
  ).toBeFocused();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(
    390,
  );
  await page.keyboard.press("Escape");
  await page
    .getByRole("button", { name: "Weekly briefing", exact: true })
    .click();
  await expect(page.locator(".brief table").first()).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(
    390,
  );
});

test("workstream activity uses five real weekly counts and detail survives reload", async ({
  page,
}) => {
  await page.goto("/sample.html?view=workstreams");
  const snapshot = await (await page.request.get("/sample-data.json")).json();
  const first = snapshot.workstreams.workstreams[0];
  const card = page.locator(`[data-ws="${first.id}"]`);
  const expected = first.counts
    .map((count, i) => `${snapshot.workstreams.weeks[i]}: ${count} events`)
    .join("; ");
  await expect(card.getByRole("img")).toHaveAttribute("aria-label", expected);
  await card.click();
  await expect(
    page.getByRole("heading", { name: first.name, exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("heading", { name: first.name, exact: true }),
  ).toBeVisible();
});
