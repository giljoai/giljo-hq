# Getting Started

*For users already signed in to the Giljo HQ (a GiljoAI product) dashboard. Last updated: 2026-07-17.*

This guide walks through five steps to run your first project: set up your tools, create your first product, create and stage a project, run it in your AI coding tool, and monitor it to completion.

---

## Quick Setup

The **Setup Wizard** opens automatically the first time you sign in (rerun it any time from **Tools → Startup**). It walks through four steps:

| Step | What happens |
|---|---|
| **Choose Tools** | Pick one or more AI coding tools: Claude Code, Codex CLI, Gemini CLI, Antigravity CLI, OpenCode, or a generic MCP client. You can add the rest later. |
| **Connect** | The wizard walks through your chosen tools one at a time, showing a one-command setup for each. The status card flips green by itself the moment a tool connects — there is nothing to click. Already set a tool up? Choose **"I already configured this"** to move on. |
| **Install** | Ask your tool to run `giljo_setup`. This installs the `/giljo` skill and your agent templates. |
| **Launch** | You're all set. Three cards let you create your first product, open the dashboard, or read this guide. |

Each tool's status turns green on its own once it connects. If you'd rather check by hand, run `/mcp` in your CLI tool and confirm `giljo_hq` is listed as Connected.

To add or reconnect tools later, open **Tools → Connect** — it is a single directory of your connected tools with live status, and **+ Add a tool** starts the same one-at-a-time flow.

> **About `giljo_setup`.** Run it from inside your AI tool, not the dashboard. It installs the `/giljo` skill and, when you have no agent templates yet, your agents too. Later runs refresh your skills and ask before replacing any agent templates you have customized.

---

## Create Your First Product

When the wizard finishes, an **animated welcome tour** opens automatically. It is a short, skippable walkthrough that remembers where you left off, and it ends by asking how you want to create your first product. You get four ways to start:

- **Point an agent at an existing codebase** — the fastest path, with no typing: one prompt, and your connected agent reads the repository, writes the vision document, and fills in the product card for you.
- **Shape a new idea in a guided interview** — your agent asks a few questions and turns your answers into a product.
- **Upload a vision document** — drop in a `.md` or `.txt` file describing your architecture, API design, or spec.
- **Fill in the form yourself** — the classic product form, for when you would rather type it all in.

You can also create a product any time from **Products → New Product** in the left sidebar, and a connected agent can create one for you from a single prompt without the form ever opening.

### The product form

A Product is the context container for everything you build — all projects and agents draw context from it. The form has these tabs:

| Tab | Fields |
|---|---|
| **Product Setup** | Product name (required); upload vision documents (`.md`, `.txt`) |
| **Product Info** | Codebase folder path, description, core features, brand guidelines |
| **Tech Stack** | Programming languages, frontend and backend frameworks, databases, infrastructure, target platforms |
| **Architecture** | Primary pattern, design patterns, API style, architecture notes, coding conventions |
| **Testing** | Quality standards, testing strategy, coverage target, testing frameworks |

**Vision analysis is the default path.** When you add a vision document, your AI coding tool analyzes it and populates the product fields for you — the Setup tab walks you through **Stage analysis → Analyzing… → Next**, and the remaining tabs unlock once analysis completes. Analysis also fills in the **Codebase Folder** automatically when it can determine your project path, with a visible way to skip that field. Prefer to type everything yourself? Tick **Skip** to bypass analysis and fill the form by hand.

You do not need to fill every field before saving — start with the name and add context over time. Only one product can be active at a time; activating a product returns you to the Home page.

---

## Create and Stage a Project

Open **Projects** in the left sidebar and create a project:

1. Click **New project**.
2. Give it a **Name** and **Description** in plain language — what you want built, the requirements, the constraints.
3. Set the **Project Type** for its taxonomy badge (for example BE, FE, API). The series number fills in the next available value for that type.
4. Save.

Open the project to reach its two tabs, **Staging** and **Implementation**. On the **Staging** tab, choose an **Execution Mode** (a read-only chip shows the coding tool the wizard detected for you):

- **Multi-Terminal** — each agent gets its own prompt, run in separate terminal sessions.
- **Subagent** — one main agent spawns its subagents within a single session.

Click **Stage Project**. GiljoAI assembles a structured prompt from your product context, 360 Memory, project description, and agent templates, and copies it to your clipboard.

---

## Run It in Your Tool

1. Open your AI coding tool and paste the staged prompt.
2. Your agent connects to GiljoAI and plans the mission.
3. Back in the dashboard, switch to the project's **Implementation** tab.
4. Copy the implementation prompt from there and paste it into your tool.
5. Work begins: agents read their assigned jobs, build todo lists, and coordinate through the Message Hub.

GiljoAI never calls an AI model itself — it assembles context and protocol; your AI coding tool does the thinking.

---

## Monitor and Close Out

The project's **Implementation** tab shows live agent activity:

- Agent status (waiting, working, blocked, sleeping, complete — the User Guide has the full list)
- Step progress (for example 6/6)
- Duration per agent (ticks live while an agent is active)
- A **Messages Waiting** count for each agent

Talk to your agents from the message composer — **Broadcast** to all or **Direct** to one — or open the full conversation in the **Message Hub**.

If an agent needs a decision from you mid-run, a **Decision Required** banner appears. Check in with the orchestrator, then click the banner to open the decision dialog and pick an option — that is the only place approvals are decided.

When every agent has finished, a **Review project** button appears (the banner shows **"Saving project memory…"** while the 360 Memory entry is written). Click **Review project** to see the closeout summary, then **Close** — you return to the Projects page. You can reopen the summary any time from the **"Project Completed and Closed"** badge.

Your next project starts with this accumulated 360 Memory automatically.

---

## What's Next

**Tune your product context.** If the context drifts from the real codebase, use the **Tune Context** button on a product card. Pick the sections to refresh, generate a prompt, and paste it into your AI coding tool; the agent researches the drift and, with your approval, applies the changes.

**Customize your agents.** Go to **Tools → Agents**. Edit each agent's **Role & Expertise**, or use **Add Default Agents** to re-add the starter set (your edits are kept). Sync your templates to your tool by running `giljo_setup` and choosing "Agents only". You have 16 active slots — 15 custom agents plus the reserved orchestrator.

**Plan with the Roadmap.** Open **Roadmap** to see your product's projects and tasks ranked for risk and effort by your agent. Click **Refresh Roadmap** to copy a prompt into your agent, then drag items to reorder.

**Capture tasks, create projects, and look things up from your tool** using the `/giljo` skill:

```
/giljo a task for the last three things we discussed, mark them high priority
/giljo a project for the authentication gaps, mark it as backend work
/giljo what's the BE-0042 project about?
/giljo show me open FE tasks
```

---

## Troubleshooting

**A "Skills out of date" banner appears:**
- Run `giljo_setup` in your AI coding tool to refresh your skills and agent templates. If a setup download reports itself stale, re-run `giljo_setup` for a fresh copy.

**An agent shows "Silent" status:**
- Turn on **Auto Check-In** on the project's Implementation tab to send periodic check-in nudges; pick an interval (5–60 minutes) that matches your pace.

**The Implementation tab is not updating:**
- Check the connection indicator in the navigation. A red icon means the live connection dropped — click it and use **Force Reconnect**.

> [!CE]
> The remaining items apply to self-hosted Community Edition. On hosted GiljoAI, your server, database, and updates are managed for you.

**"Connection refused" when your AI tool tries to reach MCP:**
- Confirm Giljo HQ is running (`python startup.py`).
- Check the API key in your tool's MCP configuration.
- Confirm port 7272 is not blocked by your firewall.

**The Setup Wizard won't open:**
- Run `python startup.py --setup` to force it, or `python startup.py --verbose` to watch startup logs live.

**Database connection errors:**
- Confirm PostgreSQL is running (`pg_isready`) and the credentials in your `.env` file are correct.

**After a Community Edition update:**
- Run `git pull` and restart the server so your build, skills, and agents are current (migrations apply automatically on restart).

**Need help?** Email support@giljo.ai.
