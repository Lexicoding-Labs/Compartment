/* Run against a local release test deployment. Browser and model use synthetic audit data. */
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const assert = require("node:assert/strict");
(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.CHROMIUM,
    headless: true,
  });
  try {
    const page = await browser.newPage({
      viewport: { width: 1380, height: 900 },
    });
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto(process.env.CONTROL_URL);
    await page.getByLabel("Operator token").fill(process.env.OPERATOR_TOKEN);
    await page.getByRole("button", { name: "Open console" }).click();
    await page.getByRole("button", { name: "Departments" }).click();
    await page
      .getByRole("button", { name: /Execution & Integrations/ })
      .click();
    await page.getByRole("button", { name: /Ticket operations/ }).click();
    assert.match(
      await page.getByLabel("Role instructions").inputValue(),
      /Ticket operations/,
    );
    await page.getByRole("button", { name: "Operations", exact: true }).click();
    await page.getByRole("button", { name: "New audit", exact: false }).click();
    await page.getByRole("button", { name: "Start audit" }).click();
    await page
      .getByRole("button", { name: "Request ticket approval" })
      .waitFor();
    await page.getByRole("button", { name: "Request ticket approval" }).click();
    await page.getByRole("button", { name: "Approve exact ticket" }).click();
    await page
      .getByRole("button", { name: "Accept reviewed audit" })
      .click({ timeout: 180000 });
    await page.getByRole("button", { name: "Evidence", exact: true }).click();
    await page
      .getByRole("button", { name: /verify result/ })
      .first()
      .click();
    await page
      .locator("section.inspect pre")
      .filter({ hasText: '"pass": true' })
      .waitFor();
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.getByRole("button", { name: "Download evidence" }).click(),
    ]);
    assert.match(download.suggestedFilename(), /compartment-.+\.zip/);
    await page.getByRole("button", { name: "Tasks", exact: true }).click();
    if (process.env.CONSOLE_SCREENSHOT)
      await page.screenshot({ path: process.env.CONSOLE_SCREENSHOT });
    await page.setViewportSize({ width: 390, height: 844 });
    assert.ok(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth + 1,
      ),
      "Mobile layout overflows",
    );
    assert.deepEqual(errors, []);
    console.log(
      "Console sign-in, roster, audit, resolution, approval, acceptance, evidence, download and mobile width passed.",
    );
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e.message);
  process.exit(1);
});
