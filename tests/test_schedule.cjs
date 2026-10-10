// Run with Node.js and Playwright available: node tests/test_schedule.cjs
const { chromium } = require("playwright");
const fs = require("node:fs");
const path = require("node:path");
const assert = require("node:assert/strict");

(async () => {
  const browser = await chromium.launch({ headless: true, channel: process.env.TEST_BROWSER_CHANNEL || undefined, executablePath: process.env.TEST_BROWSER_EXECUTABLE || undefined });
  try {
    const page = await browser.newPage();
    await page.setContent('<form id="policy-form"><p id="schedule-error"></p><div id="schedule-grid"></div></form>');
    const source = fs.readFileSync(path.join(__dirname, "../dashboard/static/app.js"), "utf8");
    await page.addScriptTag({ content: source.slice(0, source.indexOf("async function api(")) });
    await page.evaluate(() => buildScheduleEditor());
    const result = await page.evaluate(() => {
      const form = el("policy-form");
      const split = "0".repeat(16) + "1".repeat(4) + "0".repeat(8) + "1".repeat(4) + "0".repeat(16);
      const original = [split, "0".repeat(48), "1".repeat(48), "01".repeat(24), "0".repeat(47) + "1", split, split];
      showSchedule(original);
      const roundTrip = scheduleFromForm(form);
      const monday = el("schedule-grid").children[0];
      monday.querySelector(".schedule-controls button").click();
      const afterRemove = scheduleFromForm(form)[0];
      monday.querySelector(".schedule-controls button").click();
      const empty = scheduleFromForm(form)[0];
      monday.lastElementChild.click();
      const range = monday.querySelector(".schedule-controls");
      setScheduleTime(form, range.dataset.start, "14:30");
      setScheduleTime(form, range.dataset.end, "13:00");
      const invalid = !validateSchedule(form, false);
      setScheduleTime(form, range.dataset.start, "23:30");
      setScheduleTime(form, range.dataset.end, "00:00");
      return { original, roundTrip, afterRemove, empty, invalid, midnight: scheduleFromForm(form)[0] };
    });
    assert.deepEqual(result.roundTrip, result.original, "Saving must preserve disjoint slots");
    assert.equal(result.afterRemove, "0".repeat(28) + "1".repeat(4) + "0".repeat(16));
    assert.equal(result.empty, "0".repeat(48));
    assert.equal(result.invalid, true);
    assert.equal(result.midnight, "0".repeat(47) + "1");
    console.log("Schedule browser checks passed: round-trip, removal, validation, midnight.");
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
