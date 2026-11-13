// Cron trigger -> GitHub workflow_dispatch for scheduled.yml. See wrangler.toml.
export const JOBS = {
  "17 */3 * * *": "weather",
  "7 12,18 * * *": "scoring",
  "27 11 * * *": "311",
  "47 10 * * SUN": "311-full",
  "37 9,15 * * *": "closures",
};

export async function dispatch(env, job, fetchImpl = fetch) {
  if (!env.GITHUB_DISPATCH_TOKEN) throw new Error("GITHUB_DISPATCH_TOKEN secret is not set");
  const url = `https://api.github.com/repos/${env.GITHUB_REPO}/actions/workflows/${env.GITHUB_WORKFLOW}/dispatches`;
  const init = {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GITHUB_DISPATCH_TOKEN}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "winterpath-scheduler",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ ref: env.GITHUB_REF, inputs: { job } }),
  };
  // One retry on network errors or 5xx; 4xx (bad token, bad input) fails at once.
  for (let attempt = 1; ; attempt++) {
    let res;
    try {
      res = await fetchImpl(url, init);
    } catch (e) {
      if (attempt >= 2) throw e;
      continue;
    }
    if (res.status === 204 || res.status === 200) return res.status;
    const text = (await res.text()).slice(0, 300);
    if (res.status < 500 || attempt >= 2) throw new Error(`dispatch ${job}: HTTP ${res.status} ${text}`);
  }
}

export default {
  async scheduled(event, env, ctx) {
    const job = JOBS[event.cron];
    if (!job) throw new Error(`no job mapped to cron '${event.cron}'`);
    const status = await dispatch(env, job);
    console.log(JSON.stringify({ cron: event.cron, job, status, at: new Date(event.scheduledTime).toISOString() }));
  },
};
