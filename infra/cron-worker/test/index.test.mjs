import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import worker, { JOBS, dispatch } from "../src/index.js";

const env = { GITHUB_DISPATCH_TOKEN: "t", GITHUB_REPO: "o/r", GITHUB_WORKFLOW: "scheduled.yml", GITHUB_REF: "main" };

test("wrangler.toml crons match JOBS exactly", () => {
  const toml = readFileSync(new URL("../wrangler.toml", import.meta.url), "utf8");
  const block = toml.match(/crons = \[([\s\S]*?)\]/)[1];
  const crons = [...block.matchAll(/"([^"]+)"/g)].map((m) => m[1]);
  assert.deepEqual(crons.sort(), Object.keys(JOBS).sort());
  assert.ok(crons.length <= 5, "free plan allows 5 cron triggers");
});

test("every job is a workflow_dispatch option in scheduled.yml", () => {
  const yml = readFileSync(new URL("../../../.github/workflows/scheduled.yml", import.meta.url), "utf8");
  const opts = yml.match(/options: \[([^\]]+)\]/)[1].split(",").map((s) => s.trim().replace(/"/g, ""));
  for (const job of Object.values(JOBS)) assert.ok(opts.includes(job), job);
});

test("dispatch posts the job to the workflow", async () => {
  let seen;
  const status = await dispatch(env, "scoring", async (url, init) => {
    seen = { url, init };
    return new Response(null, { status: 204 });
  });
  assert.equal(status, 204);
  assert.equal(seen.url, "https://api.github.com/repos/o/r/actions/workflows/scheduled.yml/dispatches");
  assert.deepEqual(JSON.parse(seen.init.body), { ref: "main", inputs: { job: "scoring" } });
  assert.equal(seen.init.headers.Authorization, "Bearer t");
});

test("4xx fails without retry; 5xx retries once", async () => {
  let n = 0;
  await assert.rejects(dispatch(env, "weather", async () => (n++, new Response("bad", { status: 401 }))), /HTTP 401/);
  assert.equal(n, 1);
  n = 0;
  const s = await dispatch(env, "weather", async () => (n++ === 0 ? new Response("", { status: 502 }) : new Response(null, { status: 204 })));
  assert.equal(s, 204);
  assert.equal(n, 2);
});

test("missing token and unknown cron fail loudly", async () => {
  await assert.rejects(dispatch({ ...env, GITHUB_DISPATCH_TOKEN: "" }, "weather"), /not set/);
  await assert.rejects(worker.scheduled({ cron: "0 0 * * *", scheduledTime: 0 }, env), /no job mapped/);
});
