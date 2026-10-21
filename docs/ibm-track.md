# IBM Track: Rebuilding in IBM's Environment

We're on the IBM track of the GSA MCP hackathon. IBM wants the MCP server built
on their tools: the **IBM Bob IDE** on a TechZone VM, with agents in
**watsonx Orchestrate (wxO)**. They set weekly milestones.

We built the Federal Courts Analyst first in its own repo. Rather than
lift-and-shift it, we're rebuilding it in a new, smaller repo (`courts-mcp`) at
the pace of those milestones. **The original repo is the reference**: the finished design, data pipeline and tools we port from. This
file tracks the IBM effort so the team (and Claude, in future sessions) knows
where things stand. Eventually it's also what we turn into prompts for Bob to
port pieces across.

| | |
| --- | --- |
| New repo | [techsur-solutions/courts-mcp](https://github.com/techsur-solutions/courts-mcp) (private, team repo) |
| Reference repo | [syedaun-techsur/federal-courts-analyst](https://github.com/syedaun-techsur/federal-courts-analyst) |
| Started | 2026-10-21 |

## The two IBM tools

**IBM Bob** is IBM's AI coding IDE (VS Code–based, with an AI chat). Each
participant gets their own RHEL VM with Bob installed, reached through TechZone.
This is where we write the MCP server.

**watsonx Orchestrate** is IBM's platform for building AI agents: a model,
instructions and tools, with a chat UI. An MCP server gets in as a **toolkit**:
wxO reads its tool list and you attach the tools to an agent. Our server is the
hands; the wxO agent is the brain and the chat. Judges will see the agent.

Access instructions come from the IBM team's email (two TechZone events, one per
tool). Ask the team for it rather than copying access codes here.

## Environments

### Bob VM

Reached at `vdi.cloud.techzone.ibm.com/guacamole` → IBM Cloud → "IBM Cloud VPC
VSI - Bob IDE". It offers a **VNC Desktop** (for Bob) and an **SSH** terminal.

| Item | State (Syed's VM, 2026-10-21) |
| --- | --- |
| OS | RHEL 9.6, user `itzuser`, has `sudo` |
| Python | system 3.9.21 (too old for FastMCP); **3.12.15 via uv** |
| uv | 0.13.4, installed to `~/.local/bin` |
| git | 2.47.3; SSH key `~/.ssh/id_ed25519` added to GitHub as "Bob VM" |
| Containers | podman 5.4.0 (no docker) |
| Not installed | `ibmcloud` CLI, `gh` |
| Project | `~/projects/courts-mcp`, remote `git@github.com:techsur-solutions/courts-mcp.git` |

Tips:
- **Clipboard:** you can't paste from your Mac straight into the VNC screen.
  Press **Ctrl+Cmd+Shift** (Ctrl+Alt+Shift on Windows) to open Guacamole's side
  menu and use its Clipboard box, in both directions. The SSH terminal pastes more
  easily than VNC.
- **Paste one command at a time.** RHEL offers to install missing commands
  ("Install package …? [N/y]") and that prompt swallows the next pasted line.
- TechZone VMs expire, so **push to GitHub often**. GitHub is the source of truth.

### Setting up a teammate's VM

Once you have your own Bob VM (from the IBM access email), set it up for the
project like this. Run the commands in the VM terminal **one at a time**.

**Before you start:** ask Syed to add you to the
[techsur-solutions/courts-mcp](https://github.com/techsur-solutions/courts-mcp)
repo, and accept the invite.

1. **Install uv and Python 3.12.** The VM's system Python is 3.9, which is too old for FastMCP.
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```
   ```bash
   source ~/.bashrc
   ```
   ```bash
   uv python install 3.12
   ```
2. **Create an SSH key for GitHub.**
   ```bash
   ssh-keygen -t ed25519 -C "bob-vm" -f ~/.ssh/id_ed25519 -N ""
   ```
   ```bash
   cat ~/.ssh/id_ed25519.pub
   ```
   Copy the printed line out through the Guacamole clipboard (see Tips). On
   GitHub, go to Settings → SSH and GPG keys → New SSH key, title it "Bob VM",
   and paste. If the org uses SSO, click **Configure SSO** next to the key and
   authorize it for techsur-solutions.
3. **Check that GitHub accepts the key.** Type `yes` at the fingerprint prompt. You
   should see "Hi <you>! You've successfully authenticated."
   ```bash
   ssh -T git@github.com
   ```
4. **Tell git who you are.** Use the email on your GitHub account.
   ```bash
   git config --global user.name "Your Name"
   ```
   ```bash
   git config --global user.email "you@techsur.solutions"
   ```
5. **Clone the repo and install its dependencies.** `uv sync` reads the
   repo's lockfile and Python version.
   ```bash
   mkdir -p ~/projects && cd ~/projects && git clone git@github.com:techsur-solutions/courts-mcp.git
   ```
   ```bash
   cd ~/projects/courts-mcp && uv sync
   ```
6. **Check the server runs.** It should list the tools and print a result.
   ```bash
   uv run python src/courts_mcp/check.py
   ```
7. **Open it in Bob.** Go to File → Open Folder → `/home/itzuser/projects/courts-mcp`.

Work on a branch and open a pull request, rather than pushing to `main`
directly, so teammates don't overwrite each other.

### watsonx Orchestrate

- The instance lives in an IBM Cloud account `itz-saas-<###>` (joined by email
  invite). Go to Resource list → AI / Machine Learning → `wxo-…`. The service page
  gives the instance URL and API key for the ADK.
- **Up to 10 participants share one instance.** Prefix toolkits and agents
  with something unique (e.g. `courts-…-syed`) so they don't collide with anyone else's.
- Scripted registration uses the Orchestrate ADK:
  `pip install ibm-watsonx-orchestrate`.

## Workflow

1. Build in Bob on the VM, in the new repo, and push often.
2. Port from the reference repo **by milestone**: only what that week needs, working end
   to end, then move on.
3. Get the round trip to wxO working early, even with a trivial tool. After that, each
   new tool is just "add it, re-import the toolkit."
4. Cycle per change: write the tool → test it locally (`check.py` or pytest, MCP
   Inspector) → push → re-import the toolkit into wxO → ask the agent → fix.
5. Claude (on a Mac, in the reference repo) plans each step, explains or extracts
   reference code, and handles the wxO/ADK side. It can't drive Bob on the VM.

## Milestones

### Week 1 (current)

| # | Milestone | Status |
| --- | --- | --- |
| 1 | Write one custom tool for your server | In progress: bare server with a `hello` tool runs and is pushed; real tool next |
| 2 | Deploy your server on your cloud environment | Not started (target to confirm, see open questions) |
| 3 | Build an agent and test the use of the custom tool on your server | Not started |

**Week 1 custom tool (proposed): `get_official_figure`, simplified.** One
measure, one court, one fiscal year: return the latest-edition value plus
the first-published value and edition. That carries the project's core idea
(the official number changes between editions) in one tool. Reference:
[`tools/get_official_figure.py`](https://github.com/syedaun-techsur/federal-courts-analyst/blob/main/src/courts_analyst/tools/get_official_figure.py) and
[`core/official.py`](https://github.com/syedaun-techsur/federal-courts-analyst/blob/main/src/courts_analyst/core/official.py) in the reference repo. The showcase example is national weighted
civil filings per judgeship for FY2020: first published as 554 (JB-2020),
revised to 322 (JFF-2023 onward).

**Data question for this tool:** the DuckDB catalog (`data/build/courts.duckdb`)
in the reference repo is built locally and gitignored, so cloning it doesn't bring the data. Options:
- Export a small CSV from it (one row per measure × court × year with latest
  and first-published value and edition: about 28,000 rows, 1,454 of them
  revised) and commit that to the new repo. This is the simplest option for week 1.
- Rebuild on the VM with `make data-tables` (about 4 min of downloads). This brings
  the whole pipeline along, which is more than week 1 needs.

### Later weeks

Not announced yet. Add them here as they arrive.

## Deployment options

The GSA template's kits in the reference repo's [`deploy/ibm/`](https://github.com/syedaun-techsur/federal-courts-analyst/tree/main/deploy/ibm) cover wxO:
- `local-mcp-toolkit/`: stdio, runs inside wxO, no cloud setup. The data file
  has to ship with it.
- `prebuilt-image/`: Code Engine from a public image (e.g. GHCR).
- `code-engine-git-build/`: Code Engine builds from a public Git repo.
  **Our repos are private**, so this one is probably out.
- Or run the server on the Bob VM itself (it is an IBM Cloud VSI), if wxO can
  reach it over the internet.

## Open questions

- Where should the server be deployed for milestone 2: the Bob VM or Code
  Engine in the `itz-saas` account? Ask the IBM team.
- Is reusing code written before the IBM track allowed, or should it be built
  fresh in their environment?
- Do judges look at Bob usage itself (chat history, modes)?
- Where does Bob's AI chat live in this version of the IDE? (Not yet found.)

## Progress log

### 2026-10-21
- Got access to the Bob VM and wxO.
- On the VM: installed uv and Python 3.12. Created `~/projects/courts-mcp` with
  `uv init` and `uv add fastmcp`.
- uv 0.13 made a packaged `src/` layout, so the code lives in `src/courts_mcp/`.
- Added `server.py` (FastMCP server `courts-mcp` with a placeholder `hello`
  tool) and `check.py` (in-memory `fastmcp.Client` that lists tools and calls
  `hello`). `uv run python src/courts_mcp/check.py` passes.
- Created the team repo `techsur-solutions/courts-mcp`, set up an SSH key from the
  VM, and pushed the first commit.
- Next: the week 1 custom tool (decide the data approach above).
