export default {
  async scheduled(_controller, env) {
    const response = await fetch(
      "https://api.github.com/repos/nvbangg/awesome-morphe/actions/workflows/ci.yml/dispatches",
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${env.GITHUB_TOKEN}`,
          "User-Agent": "AwesomeMorphe-Scheduler",
          Accept: "application/vnd.github+json",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ ref: "main" }),
      },
    );
    if (!response.ok) {
      throw new Error(`GitHub dispatch failed: HTTP ${response.status}`);
    }
    console.log("Sync workflow dispatched");
  },
};
