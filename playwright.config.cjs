const liveURL = process.env.PULSE_BASE_URL;
const { defineConfig } = require("@playwright/test");
module.exports = defineConfig({
  testDir: "./tests/browser",
  timeout: 30000,
  workers: 1,
  use: {
    baseURL: liveURL || "http://127.0.0.1:8952",
    trace: "retain-on-failure",
  },
  webServer: liveURL
    ? undefined
    : {
        command: "python scripts/serve_sample.py --port 8952",
        url: "http://127.0.0.1:8952/sample.html",
        reuseExistingServer: !process.env.CI,
      },
});
