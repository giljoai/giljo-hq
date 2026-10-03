# Giljo HQ: User Guide

*Last updated: 2026-10-01*

This guide covers every page and UI element in Giljo HQ, a GiljoAI product. Read from top to bottom on first use, or jump to the section you need.

> **Self-hosting (Community Edition)?** The setup, optional HTTPS (through a reverse proxy), and server-startup instructions are gathered at the end under **Self-Hosting & Network Setup**. Hosted (SaaS) users can skip that section entirely — your server and certificates are managed for you.

---

## Home Page

The Home page is the entry point after login. It shows a personalized greeting, your Quick Launch cards, your agent team roster, and either a setup prompt or your recent projects. Activating any product automatically returns you here, so Home is the per-product starting point.

### Quick Launch Cards

Cards appear at the top of the page. Their content adapts based on your onboarding state:

| Condition | Cards shown |
|---|---|
| Setup not complete | Quick Setup, Learn, New Product (as needed) |
| No product created | New Product (with attention animation) |
| Product exists, no projects | New Project + two starter templates (see below) |
| Active projects running | Active Projects, Dashboard, Tasks & Handovers, Look Up |

Each card shows a title, description, and optional badge. Cards with a slash command badge (e.g. `/giljo add project`, `/giljo`) indicate that operation is also available from your AI coding tool. Clicking a card navigates to the relevant page or opens the relevant overlay.

The **Look Up** card (green, magnifier icon, `/giljo` badge) is a read-only lookup — it lets your AI tool find existing projects and tasks without write access.

### Starter Templates

When you have an active product but have not created any projects under it yet, two preset starter template cards appear next to **+ Create your first project**:

- **Bootstrap a new product** — scaffolds folders, README, and `requirements.txt`, and proposes follow-up development projects.
- **Import an existing product** — analyzes an existing codebase and seeds 360 Memory.

Clicking a template auto-creates a pre-filled project and takes you to the Projects page. Once a product has had its first project created, these cards do not reappear for that product (even if you later delete all its projects).

### Your Team

A team roster shows the orchestrator plus your active agent templates. Each agent shows a tinted initial badge, display name, and description. Empty slots show a plus icon. The slot count (e.g. "3 / 16 slots") appears in the header — that is one reserved orchestrator slot plus up to fifteen of your own agents. Click "Manage" to go to Agent Template settings.

### Onboarding Flow

The page detects your setup state on mount and opens the appropriate step:

- First login with setup incomplete: the **Setup Wizard** opens automatically.
- Setup complete, tour not yet seen: an animated **welcome tour** opens a moment after the wizard closes.
- Returning to Home with `?openSetup=true` in the URL: the Setup Wizard opens in re-run mode.
- Returning to Home with `?openGuide=true` in the URL: the welcome tour opens directly.

The welcome tour is also reachable any time from **Tools**, under the **Startup** tab.

#### The Welcome Tour

After setup, a short animated tour introduces the product. It is a guided walkthrough, not a wall of text, and you can leave at any point with **"Skip — I'll explore on my own."** It never blocks you, and it remembers where you left off — reopen it and you resume at the same stop and the same starting choice.

A rail down the left lets you jump between six stops:

1. **How it works** — your own AI tools do the thinking; GiljoAI keeps the thread and briefs them at every session start. GiljoAI never runs an AI model itself.
2. **Product & crew** — define your product once and the whole agent crew inherits it.
3. **Missions** — how work is framed as missions, not one-off chats.
4. **360 Memory** — every project makes the next one smarter.
5. **The destination** — a preview of your working dashboard.
6. **Get started** — choose how to create your first product.

The final stop offers four ways to start, from fastest to most manual:

- **I have an existing codebase** (fastest, no typing) — one prompt and your connected agent reads the repo, writes the vision document, and fills in the product card for you.
- **I have an idea — help me shape it** — a short guided interview turns your idea into a product.
- **I have a vision document** — drag in a `.md` or `.txt` brief and it becomes your product.
- **I'll fill it in myself** — opens the classic product form.

The first three hand a prompt to your connected agent, which proposes a product for you to review and activate. The last one leaves the tour and opens the product form directly.

#### Setup Wizard Steps

The wizard has four steps shown in a progress bar:

| Step | Label | What happens |
|---|---|---|
| 1 | Choose Tools | Pick one or more of the six AI coding tools you use (you can add the rest later) |
| 2 | Connect | The wizard walks you through your chosen tools one at a time, with a live status card that flips green the moment each one connects |
| 3 | Install | Ask your tool to run `giljo_setup`, which installs the `/giljo` skill and writes the Giljo HQ marker block into your project's `CLAUDE.md` / `AGENTS.md` |
| 4 | Launch | Confirm you are set up and jump to creating your first product |

The four pickable tools are **Claude Code**, **Codex CLI**, **OpenCode**, and **Generic MCP client** (which covers anything else that speaks open MCP). Claude Desktop and other chat clients connect a little differently — see **AI Tool Configuration (Connect)** for the exact steps. The wizard can be restarted any time from **Tools → Startup**.

### System Banners

Guidance and status banners appear in a single strip at the top of the page. Every banner leads with Gil's face and speaks to you directly — these are the same nudges that older versions showed as pop-in cards, now folded into one place. Each has one **"Go to…"** button, and dismissing a banner sticks (its state is stored server-side, so it persists across refreshes, sessions, and devices). Some banners (such as a lapsed subscription) clear only when the underlying condition is resolved. Time-based banners are re-checked periodically, so a dismissed reminder reliably comes back while it still applies — even on a server left running a long time.

Common banners:

- **Enable Git** — turn on the Git integration in your connect settings to give agents more context (retires once it is on).
- **Tune your agents** — after your first project completes, a one-time nudge to make the default agent templates and product context your own.
- **Activate your product** — shown when you have a product but none is active.
- **Context review** — about two weeks after a product's context was last reviewed, once at least one project has completed since, Gil suggests tuning it so agents stay current. You can suppress it in notification settings.

> [!CE]
> Community Edition also shows system notices for pending database migrations and available updates (the update banner points you to where to download the new version). Both editions show the skills-drift banner.

---

## Dashboard

The Dashboard shows system-wide statistics across your account.

### Stat Pills

Three stat pills appear at the top. Each pill shows a count, a mini bar chart, and a color-coded legend:

- **Status Distribution:** Total projects broken down by status (active, completed, staged, cancelled, terminated).
- **Project Types:** Projects broken down by project type (e.g. Backend, Frontend, API).
- **Agent Roles:** Total agents spawned, broken down by role type.

### Mini Stats Row

Five compact counters appear below the stat pills:

| Counter | Description |
|---|---|
| Active | Projects currently in active status |
| Tasks | Total tasks across all statuses |
| API Calls | Total FastAPI calls recorded |
| MCP Calls | Total MCP tool calls recorded |
| Commits | Git commits captured in 360 Memory |

### Projects Panel

A full-width panel shows recent projects with their status, taxonomy badge, and completion date. Click "All Projects" to go to the Projects page. Click a project's Serial badge to open the Project Review modal.

### 360 Memories and Recent Commits

Two side-by-side panels appear at the bottom:

- **360 Memories:** Recent memory entries written at project completion, with links back to their source projects.
- **Recent Commits:** Git commits extracted from 360 Memory entries, shown as SHA + message + author.

---

## Products

Products sit at the top of the hierarchy: Product - Projects - Jobs - Agents. A product represents the software you are building. All projects, tasks, agents, and memories belong to a product.

### Creating a Product

Analyzing a vision document is now the **default** way to create a product; filling every field by hand is the explicit escape hatch. Click "New Product" to open the product form. The Setup tab is **AI-first**:

1. Enter a **Name** (required).
2. Optionally attach one or more **vision documents** (`.md` or `.txt`, max 5 MB each).
3. If you attach a document, an optional **extraction-instructions** panel appears where you can steer what the AI pulls out.
4. The footer button moves through **Stage analysis → Analyzing… → Next** as the AI processes your document.

When analysis can determine your project's path on disk, it fills in the **Codebase Folder** for you, with a visible way to skip that field.

If a vision document is attached, the remaining tabs (Tech Stack, Architecture, Testing) and the **Next** button stay locked until analysis completes — a tooltip explains "Run analysis to unlock." Everything unlocks automatically when the AI finishes.

If you would rather fill in fields by hand, tick **Skip** (labeled "Not recommended") to bypass analysis and unlock all tabs immediately.

If you save a product with a name that duplicates an existing one, a blocking dialog appears ("Duplicate product name — pick a different name, or activate or rename the existing product"). Your typed fields are preserved behind the dialog.

> **Editing** an existing product never locks the tabs — the analysis gate applies only when creating a new product.

> **Prefer to skip the form entirely?** A connected AI agent can create your first product *and* write its vision document for you from a single prompt (this is what the welcome tour's "existing codebase" and "shape an idea" paths do). An agent-written product appears in the dashboard exactly like one you created by hand.

### Context Fields

The product form is organized into four tabs. Fields that are toggled on in Tools > Context become part of agent context at session start:

**Product Info tab:**
- **Description:** What the product does and who it is for.
- **Core Features:** Main functionality and capabilities.
- **Brand & Design Guidelines:** Visual style, colors, and fonts for frontend work.
- **Codebase Folder:** Local path to the codebase (used during tuning).

**Tech Stack tab:** Programming languages, frontend frameworks, backend frameworks, databases and storage, infrastructure and DevOps, target platforms.

**Architecture tab:** Primary architecture pattern, design patterns and principles, API style and communication, architecture notes, coding conventions and standards.

**Testing tab:** Quality standards, testing strategy, coverage target, testing frameworks and tools.

### Vision Documents

Vision documents are the most impactful input you can give GiljoAI. A well-written product proposal, architecture spec, or feature brief gives every agent session a shared understanding of what you are building and why. Without one, agents work from field-level context alone. With one, they understand scope, constraints, trade-offs, and intent.

Upload your product proposal, architecture overview, or design spec as `.md` or `.txt` files. After upload, your AI coding tool analyzes the document and can populate the product fields automatically. The product card shows a "docs" badge and a "chunks" count once documents are processed.

In the Product Details dialog, the **Vision Context** section shows three context-depth tiers (33% / 66% / 100%) with token estimates, plus a per-document manifest listing each file's name, **Analyzed** status, size, and **Chunked** status.

If you do not have a vision document yet, start with a one-page brief: what the product does, who it is for, the core technical decisions, and what success looks like. That single page will improve every agent interaction that follows.

#### Keeping Vision Analysis Fresh

When you edit a product whose vision documents have changed since the last analysis, a warning banner appears on the Setup tab offering a one-click action to spawn a **Context Update (CTX)** project that re-analyzes the product. If analysis is already current, an "Already fresh" message appears instead.

### Tuning

Click the tune icon on a product card to open the Tuning dialog. Tuning lets you update product context fields when they have drifted from the actual codebase.

The workflow:

1. Select the sections you want to retune (description, tech stack, architecture, core features, codebase structure, etc.)
2. Click **Generate Tuning Prompt**. A structured prompt is produced; the view scrolls to it automatically so you can copy it to your clipboard.
3. Paste the prompt into your connected AI coding tool
4. The agent scans the codebase, checks for drift between the stored context and the actual code, and presents findings section by section
5. Approve or reject each section's proposed changes in the tool's conversation
6. Approved changes are applied directly to the product fields in Giljo HQ. There is no separate review step in the dashboard

The `context_tuning` notification in the bell menu appears after a tuning pass applies changes to a product.

You can show several products at once, each in its own tab.

---

## Projects

### Creating a Project

Click "New Project" to open the project form. Each project belongs to a product: the one you're viewing, or the one you name when you create it. Fields:

- **Name (required):** Free text description of the work.
- **Description:** What this project delivers.
- **Project Type:** Taxonomy category (e.g. BE for Backend, FE for Frontend, API). Determines the taxonomy alias badge (e.g. BE-0001).
- **Series Number:** Sequential number within the type. When you pick a project type, this field auto-fills with the next available number for that type, so you do not have to look it up. The counter is scoped per product — a BE project in Product A and a BE project in Product B each have their own independent numbering.
- **Subseries:** Single-letter suffix for sub-tasks (e.g. BE-0001a).
- **Status:** Defaults to `inactive`.

Projects can also be created from your AI coding tool using `/giljo add project ...`.

### Opening a Project

In the Projects list, click a project's colored **Serial badge** (e.g. `BE-0042`) to open its Project Review. The rest of the row is selectable text, so you can copy a project's name or description without triggering navigation.

### Managing the Projects List

- A **compact view** toggle tightens the table so more projects fit on screen at once.
- Deleting a project moves it to **Deleted Projects for 10 days**, where it can be restored. After 10 days it is permanently purged. A **"Deleted projects (N)"** button opens that recovery list.
- Row actions include Activate, Deactivate, Complete, Cancel, Reopen, Review, **Mark Superseded**, Edit, Duplicate, Archive/Unarchive, and Delete.

### Project Status and Protection

Projects move through several statuses as work progresses. Two statuses lock a project from further changes:

- **Completed:** Set automatically when the orchestrator closes out the project. A completed project cannot be edited or restarted. To re-do the work, duplicate the project from the project list.
- **Cancelled:** Set manually via the Cancel action on a project. Once cancelled, the project is locked and cannot be modified. Use this when you want to abandon a project while keeping its history.

Completed and cancelled projects are protected. Any attempt to change their fields (name, description, status, etc.) will be blocked with an error.

You can also mark a project **Superseded** with a link to the project that replaced it. This keeps history navigable — the old project stays visible and points at its successor — without deleting anything.

### Running a Project on the Jobs Board

Activating a project puts it on the **Jobs** board, the one place a project is staged and run. The board has two sides:

- **Staging**: projects getting ready to run, with the filters **Activated**, **Planning** and **Staged**.
- **Implementation**: projects that are running, with the counters **Needs decision**, **Needs attention**, **Implementing** and **Review** (covered under **Jobs** below).

The board opens on **Implementation** when anything is running, and on **Staging** otherwise. Opening an active project from the Projects list, or following an older link to a project, lands on its card.

A card on the **Staging** side shows what you read before you launch: the execution mode, the detected tool, the crew size and the number of phases, then three panels. **Project description** has a pencil to edit it. **Mission** is empty until you stage, updates live while the orchestrator writes it, and is tagged once generated. **Crew** shows the agents the orchestrator chose: click one to see its role, or use the pencil beside a worker to edit its mission before launch. The Crew header also has the agent tips and the Git icon, which takes you to your integrations.

#### Choosing an Execution Mode

On a Staging card's **Run as** row you pick how the work runs. Nothing is selected for you: pressing **Stage Project** without a choice asks you to pick a mode first. There are two modes:

- **Multi-terminal** — you launch each agent in its own terminal. Phases run one after another; agents within a phase run in parallel.
- **Subagent** — one main agent spawns and manages all the others itself. This works with tools that support subagents.

Next to the mode picker, a read-only **"detected"** chip shows what GiljoAI auto-resolved from the tool you connected — a hint, not a setting you change.

Running agents unattended (**headless**) is a separate, account-level switch in your settings rather than a per-project choice. When a project runs headless, the dashboard **follows it live** on its own — you do not have to babysit each terminal.

#### Staging a Project

On the card, the stage button walks through its own states as you go: **Stage Project → Staging… → Unstage** (to back out) → **Re-Stage** (to recover a staged-but-not-yet-launched project). It is disabled once implementation has launched. **Unstage** and **Re-Stage** clear the mode choice, so the next Stage asks again. Staging generates the orchestrator prompt (your product context, 360 Memory, project description, and agent template definitions) for you to paste into your connected tool.

- **Staged:** the prompt is ready; the staged indicator shows a green checkmark in the project table.
- **Active:** the project is currently running. Several projects can be active in the same product at once.

If a staging orchestrator finishes without spawning any specialist agents, staging is blocked and the project stays re-stageable (the **Implement** button stays disabled) so you can stage it again — it will not be left in a broken state.

Once staging completes, click **Implement** on the card. It starts the project, copies the implementation prompt for you to paste into your connected tool, and moves the card to the **Implementation** side.

### Project Phases

**Implementation phase:** agents execute the plan. In multi-terminal mode, phases run one after another and agents within a phase run in parallel. In subagent mode, the orchestrator spawns and coordinates the agents itself.

**Closeout phase:** when every agent has finished, you review the project and close it out — GiljoAI writes a 360 Memory entry capturing what was built, key decisions, patterns discovered, and outcomes, and marks the project complete. That memory flows into the next project automatically. The closeout workflow is described in detail under **Jobs → Closing Out a Project** below.

---

## Roadmap

The **Roadmap** (in the left navigation) is a single ranked plan of what to build next for the product you're viewing. It pulls together the product's **inactive projects and pending tasks** and orders them, with a risk and complexity score on each. There is one roadmap per product.

### Who Ranks It

Your **AI agent** builds the roadmap — GiljoAI's server never analyzes or reorders it on its own. The page is a bridge:

1. Click **Create Roadmap** (empty) or **Refresh Roadmap** (populated). This **copies a prompt** to your clipboard.
2. Paste it into the agent connected to this account. (Tick **"Add my own instructions"** first if you want to steer it.)
3. A **"Waiting for your agent…"** banner appears while the agent works and clears automatically the moment it saves the roadmap.

Because the agent does the ranking, the risk (low / med / high), complexity (light / med / heavy), and any blocked flags all reflect its judgment, not an automatic calculation.

### Working With the List

Each item is a card showing a **PROJECT** or **TASK** badge, its status, its risk and complexity, and a **Blocked** row with the agent's reason if it flagged one. From a card you can:

- **Drag** the grip to reorder — the order saves automatically and survives a refresh.
- **Convert to Project** — promotes a task into a new project.
- **Remove from roadmap** — takes the item off the roadmap only; the project or task itself is untouched and reappears next time the agent rebuilds the roadmap.

A **"Fold in tasks"** switch filters tasks out so you see projects alone.

When you are ready to run a project from the roadmap, activate it from the **Projects** page. That lands its card on the **Staging** side of the **Jobs** board.

---

## Jobs

The **Jobs** entry in the left navigation opens the Jobs board: one card per project in flight, with live agent monitoring for every running project. The **All** tab, first in the product strip on the Jobs page, shows every product at once, one group per product with the most recently active first. Click a product tab to narrow the board to that product, and **All** to widen it again.

Each product group and each card folds with its chevron. A folded card keeps one line: the crew, steps, waiting count, elapsed time and its main button. The **View** switch sets the default: **Compact** (the default) folds every card to its one line, and cards that need you keep their coloured edge; **Detailed** opens every card. The board remembers these choices in your browser.

The board updates on its own. When an agent starts, finishes, goes quiet, gets blocked or receives a message, its card changes without reloading the page, and projects appear and leave as they start and finish.

### Agent Monitoring

On a running card each agent has one row, with the orchestrator always first:

| Part of the row | What it does |
|---|---|
| Play button | Copies the agent's launch prompt. Once used, it becomes a re-copy button that re-issues the latest prompt, for example after a disconnect |
| Agent badge | Tinted initials; hover for the agent's name, role and ids |
| Steps | Completed steps out of total (e.g. 3/8); click to open the agent's task list |
| Duration | Elapsed time since the agent started; ticks live every second while it works |
| Status | Current status with color coding (see Status Badges below). An agent nobody started well after launch shows **Not picked up** |
| Messages | Count of unread messages from this agent; click to open them |

The menu at the end of the row has **View messages**, **View agent role**, **View assigned job** and, when the agent delivered one, **Open pull request**.

A card that needs you says so in its status pill, for example **Orchestrator silent** or **Your decision needed**; hover the pill to see what to do about it.

**Jobs detail** on a card opens the full view of that project: its status banner, the proposed execution order for multi-terminal projects, and the message composer addressed to the project's orchestrator (or, for a project in a chain, the chain's conductor).

### Status Badges

Each agent displays one of the following statuses (this table doubles as the on-screen badge legend):

| Status value | Display label | Style |
|---|---|---|
| `waiting` | Waiting. | Yellow, italic |
| `working` | Working... | White, italic, animated dots |
| `blocked` | Blocked | Orange, upright |
| `awaiting_user` | Needs decision | Amber, upright (an approval is pending — see Agent Approvals) |
| `idle` | Monitoring | Steel blue, italic |
| `sleeping` | Sleeping | Soft purple, italic |
| `silent` | Silent | Orange, upright (agent stopped communicating) |
| `complete` | Complete | Green, upright |
| `handed_over` | Handed Over | Muted grey, upright |
| `decommissioned` | Decommissioned | Dark grey, upright |

An agent with `working` status shows a breathing glow animation on its badge and an expanding pulse ring.

At the moment staging finishes but before you click Implement, the orchestrator shows **Waiting** rather than Complete, so it is clear the project is paused for you to launch implementation, not finished.

### Agent Display Names

When you spawn more than one agent of the same type in a project (for example, two implementer agents), Giljo HQ automatically assigns a numeric suffix to each one: the first is "implementer", the second is "implementer-2", the third is "implementer-3", and so on. You do not need to name them manually.

### Agent Approvals (Human-in-the-Loop)

When an agent needs a decision from you mid-work, the project's card says **Your decision needed** and its **Jobs detail** shows an amber **"Needs decision"** banner: *"Check in with the orchestrator in chat, then click here to decide."*

1. Read the agent's full reasoning in your AI chat.
2. Click the banner to open the **decision dialog**, which shows the request and the available options (e.g. Approve / Reject / Defer).
3. Pick an option. **The dashboard is the one place a decision can always be made** — there is no global approvals page, and picking an option here is what unlocks the orchestrator. Your choice is delivered to the orchestrator's inbox.

The banner then confirms *"Orchestrator unlocked — Tell the orchestrator to read its message and proceed."* Nudge the orchestrator in your AI chat to check its inbox; the banner clears on its own once it does.

On an AI client that supports the newest MCP connection standard, you may instead be asked to decide right there in your chat — answering resolves the request the same way clicking the dashboard option does, so the orchestrator still unlocks and the dashboard still reflects it. Nothing changes for other clients: the request waits on your dashboard exactly as described above.

### Closing Out a Project

When every agent has finished, the card shows a **Review project** button, and **Jobs detail** guides you through closeout via the status banner at the top:

1. **"Saving project memory…"** appears briefly while the 360 Memory entry is written.
2. A **"Review project"** button then appears. Click it to open the closeout summary — the project's 360 Memory, laid out as **Summary**, **Key Outcomes**, **Decisions Made**, and **Git Commits**.
3. Click **Close**. A confirmation toast fires and you stay on the board; the reviewed project leaves it.

To look back at a finished project, click its serial badge on the **Projects** page to open **Project Review** (see below). Reopening a closeout summary and clicking **Close** there is a safe acknowledgement: it will not re-file or overwrite anything.

If a closeout ever looks stuck because the orchestrator was never staged, you can **force-close** it to free the project. A project where everything already finished always routes cleanly to the closeout summary.

### Agent Check-in Cadence

How often a waiting agent checks in for new work is now one account-level setting, not a per-project slider. Set it in **Tools → Agents → Behaviour**, next to the Agent Silence Threshold (see **Agent Behaviour** below). Agents on a harness with live wake support respond to new work instantly instead of sleeping on a timer; every other agent sleeps for the cadence you set between checks. A project staged before this change that still carries its own saved interval keeps honoring that value as an override.

---

## Project Review

Clicking a project's Serial badge (from the Dashboard or Projects page) opens the Project Review modal. This modal gives a full breakdown of how the project was executed.

The modal is organized into expandable sections:

- **Agent Jobs:** Each agent job is shown as a collapsible card. Expand it to see its assigned mission, todo list, and step progress.
- **Agent Messages:** The message traffic between agents during the project — useful for understanding why decisions were made.
- **Project Threads:** A read-only view of the project's Message Hub threads, with an **"Open in Hub"** link to jump into the full conversation.
- **Git Commits:** Commits recorded during the project (requires git integration to be enabled in Tools > Connect).
- **360 Memory:** The memory entry written at closeout.

Closeout and agent approvals are separate flows. If an agent has a pending approval when you open the closeout summary, it directs you to resolve the decision in the decision dialog first (see Agent Approvals above).

---

## Message Hub

The **Message Hub** (in the left navigation) is where you and your agents talk. You broadcast to the whole team or message one agent directly, and agents post back under their own identities as they coordinate. The nav item shows an unread-count badge and pulses when it is your turn to reply somewhere.

### Threads

Threads are grouped under two tabs, each with its own unread badge:

- **Project threads** — conversations attached to a specific project.
- **General threads** — standalone conversations not tied to a project.

Each thread row shows a `CHT-####` id (click to copy the full id), a status pill, the subject, and the time. Click a row to read its timeline on the right. Every message shows who sent it (you appear in brand yellow, agents in their role color), the time, a **Broadcast** or **Direct** chip, and an **"action required"** flag when a post needs a response.

Once a thread is open, a search box above its timeline narrows it to the messages you are looking for, matching both what was said and who said it. Clear the box to get the full conversation back.

### Reading and Replying

Type in the composer at the bottom:

- Toggle **Broadcast** (everyone on the thread) or **Direct** (pick one agent under **"To agent…"**).
- Press **Ctrl+Enter** or click **Send**.

You can reach a thread directly from a notification, from the **Open in Hub** link in Project Review, and from the Hub button or an agent's message count on a Jobs board card.

### Your Turn and the Baton

Agents pass a conversational "turn" (the baton) as they work. The Hub shows the baton **only when it is pointing at you**: a **"Your turn"** badge above the composer and a gold chip on the thread row. When you see it, replying passes the turn back so work can continue. (The Hub does not show which *agent* currently holds the turn — only your own turn is highlighted.) A directed message that needs action automatically hands the turn to whoever it is addressed to, so no separate hand-off step is needed.

### Creating and Recovering Threads

- **New Thread** needs a **Subject**; a Project and Product are optional.
- The Hub has no check-in control of its own. How often waiting agents check in for new work is the account setting **Agent Check-in Cadence** (see **Agent Check-in Cadence** under Jobs, above).
- Only **General threads** can be deleted; the **Deleted** button lists soft-deleted threads so you can restore them. Project threads follow their project's lifecycle and cannot be deleted from the Hub.

---

## Tasks & Handovers

The Tasks & Handovers page is one board holding two kinds of note. **Tasks** track technical debt, scope captures, and development notes: work that has been identified but not yet scheduled, kept separate from projects. **Handovers** record where a working session stopped, for whoever picks it up next.

### The board

Both kinds display in a filterable table. The first column is a colored **Type+Serial badge**: purple `TSK-0042` for a task, near-white `HND-9641` for a handover. A task with no type assigned shows an em-dash badge. Remaining columns include Title (with description), Status, Priority, and Created date. Click any row to open the edit dialog. Serials come from one shared counter, so a handover never duplicates a number a task already used.

Each row's overflow menu includes an **Archive/Unarchive** action. Archived items are removed from the default board view but reappear when you search or toggle **Show archived** in the action bar (they carry an **Archived** badge), and they remain available to your AI tool via `/giljo`.

### Handovers

A handover is written for someone who was not in the session, cannot ask the author anything, and has no way to tell a checked claim from a confident one. So it has to carry three sections, and the board refuses to save one that does not:

| Section | What belongs there |
|---|---|
| **Verify before trusting** | Every claim, each next to the exact command that checks it. Not "the tests pass", but the command and what a passing run prints. |
| **Waiting on the operator** | Anything that cannot move without you. |
| **Cannot testify** | What the author did **not** verify: guesses, assumptions, things they were told, things that looked fine but were never run. |

The third section is the one that matters most. A handover that lists only what went right reads exactly the same whether the author checked it or assumed it, and the next person finds out at the worst possible moment.

The statuses carry handover meanings: **Pending** is written but unread, **In Progress** means someone is verifying its claims, **Completed** means verified rather than merely read, **Blocked** means a claim turned out to be false and needs you, and **Cancelled** means a later handover superseded it.

Two things a handover will not do. It is a record of work that already happened, so **Convert to Project** is not offered on one. If a handover surfaced work still to do, create that project and leave the handover as the record of where it came from. And a handover still marked **Pending** cannot be archived, because nobody has read it yet and hiding it would remove it from the list of the one person it was written for. Move it off Pending first.

Your AI coding tool writes handovers for you: ask it to hand the session over, and it creates one with the three sections filled in.

### Categories and Priorities

**Categories:**

| Value | Purpose |
|---|---|
| `general` | Uncategorized work |
| `feature` | New functionality |
| `bug` | Defect or regression |
| `improvement` | Refactor or enhancement |
| `docs` | Documentation work |
| `testing` | Test coverage or test tooling |

**Priorities:** `low`, `medium`, `high`, `critical`

**Statuses:** `pending`, `in_progress`, `on_hold`, `completed`, `blocked`, `cancelled`

Use **On hold** (`on_hold`) to park a task you have not decided on yet. It still counts as open work, and unlike **In Progress** it does not record a start time.

Status badges use brand colors from the server's canonical status registry.

### Creating and Editing Tasks

The Create Task dialog includes an optional **Serial** number field (placeholder "auto"); leave it blank to have the next number assigned automatically. In the Edit dialog, the Serial field shows just the number (e.g. `42`), not the full alias.

Promoting a task to a project (Convert to Project) creates a new **inactive** project and does **not** deactivate the product's currently-active project — you activate the new project yourself when you are ready. A connected agent can run the same conversion itself in one step, without leaving the task's roadmap card orphaned; the new project always lands under the task's own product and arrives inactive and untyped.

### Filtering

The filter bar provides search by title, filter by status, and filter by priority. Search matches a task's title, description, **and** serial (e.g. searching `FE-0047` finds that task). All filters combine. Click "Clear Filters" to reset. Filters persist within the session but reset on page reload.

Tasks can also be created from your AI coding tool using `/giljo add task ...`. To look up tasks or projects without leaving your session, use `/giljo` — e.g. `/giljo what BE tasks are open?` or `/giljo show project BE-5040`.

---

## Tools

Navigate to **Tools** via the left navigation. Five tabs are available:

| Tab | Contents |
|---|---|
| **Connect** | Your directory of connected AI tools, API keys, and integrations (git) |
| **Agents** | Agent Template Manager: browse, create, edit, and activate agent templates; the **Behaviour** view holds the agent silence threshold and check-in cadence |
| **Context** | Context configuration: choose what grounding context agents receive and how much |
| **Notifications** | Notification position and duration |
| **Startup** | Cards to reopen the **Setup Wizard**, open this **guide** (the "Learning" card), |

### Connecting Your AI Tools (Connect)

The Connect tab is a single directory of your tools. A left rail headed **"YOUR TOOLS"** lists each one with a live status — **Connected**, **Waiting**, or **Not set up**. Click **"+ Add a tool"** to pick from the six supported tools and walk through the same one-at-a-time connect flow the Setup Wizard uses; each tool card lets you copy its connection command and, later, **Remove tool**.

The four directly supported tools are **Claude Code**, **Codex CLI**, **OpenCode**, and **Generic MCP client**. **Claude Desktop** and other chat clients are not in that pickable list — they connect either by adding GiljoAI as a connector (a one-click **browser sign-in**) or by pasting a JSON config into the client's own MCP settings.

Each tool connects one of three ways, and the card shows the right steps for the one you pick:

- **Browser sign-in** — paste one command; your browser opens for a one-click sign-in.
- **Key** — generate an API key, then paste one command.
- **Manual config** — copy a server config block into the client's MCP settings.

GiljoAI notices what kind of tool connected — a command-line tool, a chat client, or a web-based coding agent — and tailors its instructions to fit. Web coding agents, which can't hold a live terminal, hand their work back to you across pull requests.

> Some clients are allowed a smaller set of tools than others (a **core**, **standard**, or **full** profile enforced by the server), so if a connected client shows fewer GiljoAI tools than another, that is expected.

### API Keys

API keys live in the Connect tab. There is **no "create key" button** — a key is **generated automatically the first time you copy a tool's connection command**. You can hold **any number** of keys; each **expires after 90 days**. To retire one, use its **Revoke** action and confirm by typing **DELETE** in the dialog.

### Git Integration

The Git integration card (Connect tab) works with any local git repository, not just GitHub. Its "Git Setup Guide" button links to git-scm.com. Enabling it lets GiljoAI record commit history into 360 Memory.

### Agent Templates (Agents tab)

The **Agents** tab is where you shape your agent crew. **Each product has its own 16 active slots**: one is reserved for the Orchestrator (managed in Admin Settings), leaving **15 for your own agents**. The budget is per product, so a second product starts with a full 15 of its own — filling one product's roster never uses up another's.

Slots are counted by **role**, not by agent: three agents that all have the role `implementer` take one slot between them, so a second copy of a role the product already runs is free. When a product has 15 roles switched on, switching on an agent with a sixteenth role is blocked with: *"Maximum 15 active agent roles allowed for this product (currently 15). Switch another role off first."* Switch a role off to free a slot. There is **no limit on how many templates you can create** — the cap is only on how many distinct roles are *active at once, within one product*.

**Add Default Agents.** The **"Add Default Agents"** button safely re-imports the starter set into **the product you are currently viewing**, at any time. It is purely additive: your edited templates are never touched. A fresh default whose name you have already customized lands as a separate `-duplicate` copy, and defaults you already have are skipped. Imported agents arrive **switched on** — this is the "give me the standard crew" button, so the crew is ready to work rather than waiting to be turned on one at a time.

**Agents follow the product you are working in.** Every agent belongs to one product, and its active state is tracked there. Where an agent came from decides whether it starts on or off: a **new product arrives with its own full crew already switched on**, and agents from **Add Default Agents** arrive switched on too — but an agent you **create by hand arrives switched off**, ready to configure, and will not appear on your orchestrator's roster until you turn it on. The **Active here** column/switch in the templates list controls exactly that, for the product you currently have open.

**Finding templates.** Filter by free-text **Search**, by **Role**, and by **Status** (Active / Inactive). The **Updated** column reads "Added today" for an agent you just added and have not switched on yet, "Never edited" for an untouched stock agent, and the real date (with the exact time on hover) once you have changed something — newest first, so agents needing your attention sit at the top.

**Editing a template.** The editor has these fields:

- **Role** (required) — the agent's role, e.g. implementer, tester, reviewer.
- **Custom Suffix (optional)** — appended to the display name (a live preview shows the result).
- **Coding tool** — the tool this agent runs in (Claude, Codex, OpenCode, or Generic).
- **Model** and **Effort** — free-text hints passed to the agent's tool when it launches, e.g. a model name or "high". Both default to **`inherit`**, meaning "the same as the orchestrator". They are plain prose, not a validated list: a tool that cannot honour a value simply ignores it.
- **Description** — a short summary.
- **Role & Expertise** — describe the agent's specialization, expertise, and personality. This is the field that shapes how the agent behaves.

**Your agents reach your tool by themselves.** There is no export, sync, or install step, and nothing about an agent lives on your machine. Every agent your orchestrator starts is handed its own profile — role, description, tool, model and effort hints, instructions, behaviour rules, and success criteria — by the server at the moment it begins work. Edit a template here and the very next agent that starts uses the new version.

**Download a profile.** If you want to run an agent yourself rather than let the orchestrator start it, open the row menu in the agents list and choose **Download profile (.md)**. You get that agent's profile as plain Markdown, ready to paste or drop into whatever tool you like.

### Installing Skills (`giljo_setup`)

`giljo_setup` is a tool you run **from inside your AI coding tool**, not from the dashboard, and it is available in both editions. It installs the `/giljo` skill and writes the Giljo HQ marker block — the short primer, plus the binding for the product this repository belongs to — into your project's `CLAUDE.md` / `AGENTS.md`. Run it once after connecting, and again whenever your skills are out of date.

It does **not** install agents, and it has no "agents only" option: agents receive their profiles from the server, so there is nothing to push or keep in sync.

A download link is valid for a short window. If a link goes stale, just re-run `giljo_setup` to get a fresh one.

### Shaping How Agents Behave

Beyond each agent's **Role & Expertise**, two tenant-level controls shape what agents know and how the orchestrator thinks:

**Context Configuration (Tools → Context).** Choose *what* grounding context agents receive and *how much*:

- **Always on:** Product Info and Project Description.
- **Toggles:** Tech Stack, Architecture, Testing.
- **Depth:** Vision Documents at Light (33%), Medium (66%), or Full (100%); 360 Memory across the last 1, 3, 5, or 10 projects; Git History from 5 up to 100 commits (available when Git integration is on).

**Tune Context (per product).** Each product card has a **"Tune Context"** button. Pick the sections to refresh and it generates a prompt for you to run in your agent; the agent checks the stored context against the real codebase, and changes are applied **only after it confirms drift** — nothing is overwritten blindly.

**System Orchestrator Prompt (advanced).** An admin can override the orchestrator's core instructions under **Account → Danger Zone → System Orchestrator Prompt**. You can customize this **per product**, or once for **all products** — a product-specific override wins for that product, anything without one falls back to your all-products prompt, and anything without either falls back to the packaged default. While a product is selected, a line above the editor names which of the three is actually governing it and, for a saved prompt, the date it was saved; the all-products tab gives the same detail about itself. Editing either can break orchestrator coordination, so a warning is shown and a **"Restore Default"** button is always available for each. Most users never need to touch either.

### Notification Settings

The **Notifications** tab sets where notifications appear (**Position** — six corner/edge options) and how long they stay (**Display duration**, 2–10 seconds).

### Agent Behaviour

Under **Tools → Agents → Behaviour**, two account-level settings tune agent timing, saved to the database and persisted across sessions, in both editions:

- **Agent Silence Threshold (minutes)** — how long an agent can go quiet before it is marked "Silent." Raise it for a slower-inference model so it is not falsely flagged.
- **Agent Check-in Cadence (minutes)** — how often a waiting agent checks in for new work (see **Agent Check-in Cadence** under Jobs, above).

Both accept any whole number from 1 to 1440 minutes and default to 10.

---

## Admin Settings

Navigate to **Admin** via the left navigation (admin users only). The page title is "Admin Settings."

Runtime settings (git integration, network mode) are stored in the database. Changes you make here take effect immediately without restarting the server.

| Tab | Contents |
|---|---|
| **Identity** | Workspace name and slug, plus user management |
| **Network** (Community Edition) | Your server's actual live address, a pointer to the HTTPS setup guide, and the cookie domain whitelist |
| **Database** (Community Edition) | Read-only view of PostgreSQL connection settings, with a "Test Connection" button |

The **Network** tab shows the real IP address(es) and port your server is currently reachable on, and links to the HTTPS setup guide (see **Self-Hosting & Network Setup**). The Network and Database tabs appear only in Community Edition.

If your session has a stale or missing organization record, the Identity tab shows a friendly empty state ("No organization found. Please contact your administrator.") rather than a raw error. Legacy URLs `/tools/identity` and `/settings/identity` redirect here automatically.

### User Management

Giljo HQ is single-user, so the user list normally holds just your account. Attempting to add another user opens a **"Single-User License"** dialog explaining that Community Edition is licensed for single-user use and directing you to **sales@giljo.ai** for a commercial license.

> [!CE]
> A Community Edition admin can reset another local user's credentials from the user's row menu (**"Change Password & PIN"**).

> Giljo HQ is permanently single-user per tenant in both Community Edition and hosted SaaS. The "Add User" button is intentionally unavailable; a future Team tier is not planned. First-install account creation is unaffected.

---

## Account and Security

Your personal account lives under **Account** in the avatar menu, split into **Profile**, **Billing**, and **Danger Zone** tabs (hosted accounts add a **Connected Accounts** tab).

### Your Profile

The Profile tab shows your **Username** (fixed), **First Name**, **Last Name (optional)**, and **Email**. Greetings throughout the app use your first name.

- **Community Edition:** email changes apply immediately.
- **Hosted (SaaS):** changing your email starts a verification flow — a banner shows the pending address with **Resend** and **Cancel** buttons, the field stays disabled until you confirm, and a confirmation link is emailed to the new address.

> [!CE]
> The Admin/Owner badge shown next to your name is a Community Edition detail; hosted accounts, which are always single-user, do not display it.

### Password and Recovery PIN

Change your password in the Profile tab's **Password** section. **Changing it signs you out everywhere** — every other session and device is logged out, and you sign in again with the new password. Passwords must be at least **8 characters**; a very long password (over 72 bytes) is rejected with a clear message rather than a server error.

> [!CE]
> A **Recovery PIN** (exactly **4 digits**) is a Community Edition feature. If you forget your password, the PIN lets you reset it right from the sign-in screen. Set or change it in the Profile tab.

> [!SAAS]
> On hosted GiljoAI you reset your password **by email** instead of with a PIN. A **"Reset Password"** item in the avatar menu sends a reset link to your address; your current password keeps working until you complete the reset.

> [!SAAS]
> You can **sign in with Google or GitHub**, and connect or disconnect those providers under **Account → Connected Accounts**. An account created with a provider can add a password at any time.

For your safety, **changing your email, password, or recovery PIN — or generating a new API key — requires a live browser session**. An API key on its own cannot perform these account-security actions.

### Sign-In Protection

After **10 failed sign-in attempts**, an account is locked for **15 minutes** before you can try again.

### Download My Data

On **Account → Danger Zone**, the **Download my data** card exports a portable ZIP of your products, projects, vision documents, agents, memory, tasks, and configuration — with credentials redacted. It **covers every table automatically** (nothing is silently missed as the product grows) and is **version-stamped**, so older export files keep restoring correctly. Click **Generate export**; a progress bar runs and a download link valid for **15 minutes** appears with a per-model record count.

> [!CE]
> Your data lives in **your own PostgreSQL database**, so ongoing backups are yours to run — back it up like any database. The "Download my data" export is a portable snapshot, not a substitute for regular database backups.

> [!SAAS]
> "Download my data" is available to account admins. The Danger Zone also offers full self-service backups: **download your latest backup**, **save a restore point** on demand, and **request an operator-reviewed restore** (which preserves your API keys). Those controls, and how they relate to your subscription, are covered in the **Billing & Subscription** chapter shown at the end of this guide.

### Trash and Recover

Deleting things is reversible for a while:

- **Projects** stay in Deleted Projects for **10 days** before permanent purge.
- **Message Hub threads**, **vision documents**, and **agent templates** are recoverable for **30 days** after deletion.
- **Archived** is a separate, tidy-away state (used for tasks and templates) — archived items are hidden from the default view but not deleted, and you can unarchive them any time.

> [!SAAS]
> **Hosted accounts include billing and subscriptions.** Plans, checkout, cancellation, resume, switching to annual, trial behavior, backups, and account deletion are covered in the **Billing & Subscription** chapter, shown at the end of this guide on hosted accounts. The self-hosted Community Edition has no billing.

---

## 360 Memory and Follow-up Work

360 Memory entries are written by agents at project closeout. They capture what was built, decisions made, patterns found, and outcomes. Each subsequent project starts with this accumulated history available to the agent team.

### Memory Browser

The **Memory** page (in the left navigation) lets you search your product's accumulated history yourself. **Full-text search** covers every entry's summaries, key outcomes, and decisions. You can filter by **tag** or **project**, **group by project**, and sort by newest, oldest, or project sequence. The same history is available to your agents — they can search it mid-run to look up how earlier work was done, so lessons carry forward automatically.

### Reporting Follow-up Work

When an agent discovers a deferred item — technical debt, a known issue, or a decision that cannot be resolved in the current project — it creates an explicit follow-up using `mcp__giljo_hq__create_task` (for single-step items) or `mcp__giljo_hq__create_project` (for multi-step work). The returned ID is cited in `decisions_made` at closeout so the audit trail is intact.

Follow-up tasks and projects appear on your Tasks & Handovers board immediately and carry forward as first-class work items.

---

## UI Elements

### WebSocket Connection Icon

A status chip in the top navigation bar shows the real-time WebSocket connection state:

| State | Label | Color | Icon |
|---|---|---|---|
| Connected | Connected | Green | wifi |
| Connecting | Connecting... | Amber | wifi-sync (animated) |
| Reconnecting | Reconnecting (N/M) | Amber | wifi-sync (animated, pulsing) |
| Disconnected | Disconnected | Red | wifi-off |

Real-time updates recover automatically after a disconnect or server restart, so a manual refresh is rarely needed. Brief blips that recover within a couple of attempts no longer raise a toast — only a sustained outage (several consecutive failed reconnects) shows a "Connection lost" message, followed by "Connection restored" when it clears.

Click the chip to open the WebSocket panel, which shows the connection state and a **Force Reconnect** action for troubleshooting if the Jobs page ever stops updating. On screens narrower than 1024 pixels, only the icon is shown.

### Notification Bell

The notification bell appears in the top navigation bar. A badge count appears when there are unread notifications; its color indicates priority (amber for warnings, red for errors).

Notifications are stored server-side, so they persist across page refreshes and browser sessions. Each notification has its own **dismiss (X)** button that removes just that item; clicking the body of a notification marks it read and navigates to the related project (if one is linked) or page.

Notification types include:

| Type | When it appears |
|---|---|
| `api_key.expiring_soon` | An API key is within 7 days of expiring; clicking it opens Tools > Connect. Clears automatically when the key is revoked or regenerated |
| `agent_health` | An agent has been silent past the configured threshold |
| `agent_status` | An agent changed to a significant status |
| `project_update` | A project was updated or completed |
| `system_alert` | A system-level error or warning |
| `message_received` | An agent sent a message requiring attention |
| `hub.baton_handover` | An agent handed the conversation turn to you. Persisted server-side, so it survives a reload and follows you to a second device; repeated hand-offs on the same thread leave one entry, not a pile. Clicking it opens the thread with the handing-over post marked and scrolled into view. |
| `connection_lost` / `connection_restored` | WebSocket connection was lost or restored |
| `context_tuning` | Context fields were updated after a tuning pass |
| `vision_analysis` | A vision document was processed |

Click "Mark all read" to clear the unread badge.

### Skills Drift Banner

When the slash-command skills installed on your machine are older than the version your server provides, an admin-only banner appears (brand yellow). To clear it, run `/giljo_setup` in your AI coding tool — this acknowledges the current skills version. On Community Edition the banner also reminds you to `git pull` and restart the server for the latest server build. The banner resurfaces if a newer version ships later.

### About Dialog

The About dialog (from the navigation drawer) shows the live running server version and the correct edition label (Community Edition or SaaS). The "Get a License" link appears only for unlicensed Community Edition installs.

---

## Limits at a glance

The numbers you are most likely to bump into. "Edition" shows where a limit applies.

| Thing | Limit | Edition |
|---|---|---|
| Active agents | 15 of your own, plus 1 reserved orchestrator (16 slots) | Both |
| Templates you can create | Unlimited (only *active* agents are capped) | Both |
| Projects in a chain | 2 to 10 | Both |
| Vision document upload | 5 MB per file | Both |
| API keys | Unlimited; each expires after 90 days | Both |
| Password length | 8 characters minimum | Both |
| Recovery PIN | Exactly 4 digits | CE |
| Sign-in lockout | 10 failed attempts → 15-minute lock | Both |
| Task title | 255 characters | Both |
| Message Hub message | 20,000 characters | Both |
| Deleted-project recovery | 10 days before permanent purge | Both |
| Deleted thread / vision doc / agent template recovery | 30 days | Both |
| Free trial | 7 days, no card required | SaaS |
| Data kept after a trial or subscription ends | Read-only at once; deleted about 13 months after a trial ends or 12 months after paid access ends; reminder email about 30 days before | SaaS |
| Seats | 1 (Solo) | SaaS |

---

## Self-Hosting & Network Setup

> [!CE]
> This entire section is for Community Edition (self-hosted) operators. Hosted (SaaS) users can skip it — your server, HTTPS certificates, and updates are managed for you.

### Starting and Restarting the Server

Run `python startup.py` to start the server. Restarting cleanly stops any previous instance first, so you will not end up with two servers running at once. The first request after a restart is pre-warmed to reduce cold-start latency.

Run `python startup.py --verbose` to open a live log-viewer window alongside the server. On Windows this is a separate PowerShell window with color-coded lines (errors red, warnings yellow, info cyan, debug grey); on macOS/Linux it opens in a terminal window. Closing the viewer does not stop the server.

### Unattended (Headless) Install — Windows

`install.ps1` supports a non-interactive install via environment variables, useful for CI or automated provisioning:

```
GILJO_UNATTENDED=1
GILJO_PG_PASSWORD=<required>
GILJO_DB_NAME=<optional, default: giljo_mcp>
GILJO_INSTALL_DIR=<optional>
```

When `GILJO_UNATTENDED` is not set, the installer runs interactively as before.

Both `install.ps1` and `install.sh` also support a **`--repair`** mode, which safely re-runs the installer over an existing install to fix a broken or partial setup without starting from scratch.

### HTTPS and Browser Configuration

Giljo HQ serves plain HTTP. HTTPS comes from a reverse proxy placed in front of it; the server has no certificate settings of its own.

**Plain HTTP is fine on a trusted home or office LAN.** Everything works: the dashboard, live updates, banners and in-app toasts, and AI tools that use an API key.

**What HTTPS adds:**

- Browser sign-in (OAuth) from AI tools such as Claude Code, which refuse to send credentials to a non-HTTPS server (localhost is exempt).
- Operating-system desktop notifications when the tab is hidden (the in-app toast works without it).
- Safe exposure beyond your LAN. Never put plain HTTP on the internet.

**Example with Caddy** (free, handles certificates for you). Save this as `Caddyfile` and run `caddy run`:

```
https://192.0.2.50:8443 {
    tls internal
    reverse_proxy 127.0.0.1:7272
}
```

Use your server's address in place of `192.0.2.50` and your Giljo HQ port in place of `7272`. `tls internal` makes Caddy sign the certificate with its own private authority; for a real domain name, drop that line and Caddy gets a public certificate automatically.

With `tls internal`, each client must trust Caddy's root certificate (`root.crt`, in Caddy's data folder under `pki/authorities/local`). Run `caddy trust` on the machine that runs Caddy, copy `root.crt` to your other machines, and import it into the browser or system trust store. Node-based AI tools (Claude Code, Codex, OpenCode) do not read the system store: set `NODE_EXTRA_CA_CERTS` to the path of `root.crt`.

**Also set:**

- `GILJO_PUBLIC_URL=https://192.0.2.50:8443` in `.env`, so links given to agents use the HTTPS address. Restart the server after changing it.
- `FORWARDED_ALLOW_IPS=<proxy address>` for the Giljo HQ server if Caddy runs on a different machine than Giljo HQ. It defaults to `127.0.0.1`, which is right when both run together.
- Re-add your AI tools afterwards: the server address changed, so the old connection commands no longer point at it.

**Other options:** Cloudflare Tunnel (no open ports, public certificate) and Tailscale (private network with `tailscale serve` HTTPS) work the same way: they sit in front of Giljo HQ and pass the original scheme along. nginx and Traefik work too.
