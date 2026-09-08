## Glossary

Quick definitions for the terms used throughout Giljo HQ. Terms are grouped by what they describe.

**The hierarchy — how your work is organized:**

| Term | Meaning |
|---|---|
| **Product** | The software you are building. A product is the top-level container: every project, task, agent, and memory belongs to one product. It holds your context — description, tech stack, architecture, testing strategy — which agents read at the start of each session. You can work on several products at once, each in its own tab. |
| **Project** | A focused unit of work inside a product, such as a feature, a refactor, or a bug fix. A project is the thing you run: it has a description, an agent team, a mission, and a closeout that writes a 360 Memory entry. |
| **Task** | A note about work you have identified but not yet scheduled. Tasks live on the Task Board and are for capturing ideas, technical debt, and follow-ups. A task does not run agents; convert it to a project when you are ready to build it. |
| **Job** | A single agent's assignment within a running project — its role, mission, and to-do list. The Jobs page shows one row per job so you can watch each agent's status and progress. |

**Running a project — staging and implementation:**

| Term | Meaning |
|---|---|
| **Staging** | The first tab on a project's page. Pick an execution mode, then click **Stage Project** to generate the orchestrator's launch prompt; the orchestrator plans the mission and spawns the agent team from there. |
| **Implementation** | The second tab on a project's page, unlocked once staging completes. Agents do the actual work here — status, duration, steps, and messages for each one — through to closeout. |

**The agents — who does the work:**

| Term | Meaning |
|---|---|
| **Agent** | An AI worker that connects through your own AI coding tool — Claude Code, Codex CLI, Gemini CLI, Antigravity CLI, OpenCode, or any other MCP-compatible client — and does the actual reasoning and coding. GiljoAI assigns each agent its role and context; your tool and subscription do the work. |
| **Orchestrator** | The lead agent for a project. It reads your product context and 360 Memory, plans the mission, spawns the specialist agents, and coordinates them until the project closes out. |
| **Agent template** | The reusable definition behind an agent role — its role, coding tool, and identity. Manage yours in **Tools > Agents**; up to 7 of your own plus the built-in Orchestrator can be active at once. |
| **"Role & Expertise"** | The field on an agent template where you describe that agent's specialization and personality — what used to be labeled its "system prompt." |
| **Conductor** | The coordinator that drives a chain of projects — also called the chain orchestrator or master orchestrator. Unlike a project orchestrator, the conductor owns no project of its own; it only runs the chain in order, launching each project and advancing to the next. |

**Chains — running several projects together:**

| Term | Meaning |
|---|---|
| **Chain project** | Several projects linked together and run one after another under a single overarching goal, coordinated by the conductor — often just called "a chain." Holds 2 to 5 projects; multi-project, single-user. See the **Chain Projects** chapter. |
| **Linking** | The act of attaching projects together into a chain, from the Projects list or the Roadmap. |
| **Chain mission** | The overarching goal for a whole chain — the single objective all the linked projects serve together, distinct from each project's own per-project mission. Shown as **"Multi project mission"** during staging. |

**Message Hub — talking with your agents:**

| Term | Meaning |
|---|---|
| **Message Hub** | The messaging center at **Message Hub** in the left navigation. Read and reply to threads here; agents post under their own identity. |
| **Thread** | A single conversation. A **project thread** is bound to one project (the **Project threads** tab); a **general thread** stands alone (the **General threads** tab). Reply Broadcast (everyone on the thread) or Direct (one agent). |
| **Baton** | Marks whose turn it is to act in a thread. When it is handed to you, the thread and composer show a **"Your turn"** badge — reply to continue. Only your own turn is shown; there is no indicator for which agent currently holds it. |

**Finding your work:**

| Term | Meaning |
|---|---|
| **Roadmap** | A ranked queue, one per product, of your inactive projects and pending tasks. Your AI agent scores each item for risk and complexity and writes the ranking; you drag to reorder, then Activate a project or Convert a task. |
| **Memory browser** | The search page at **Memory** in the left navigation — full-text search your product's accumulated 360 Memory entries by keyword, tag, or project. |
| **Vision document** | A file you upload, or one your agent writes for you, describing your product. It feeds your product's context automatically instead of you filling every field by hand. |

**Goals and memory:**

| Term | Meaning |
|---|---|
| **Mission** | What an agent or project is trying to achieve. A project's mission is planned by its orchestrator from your description and context; each agent then works its own part of that mission. |
| **360 Memory** | The record written automatically at the end of each project: what was built, key decisions, patterns discovered, and outcomes. Your next project starts with this accumulated history available to the agent team, so context carries forward instead of starting blank each time. |

**Archive and trash:**

| Term | Meaning |
|---|---|
| **Archived** | Hidden from the default view without being deleted — used for tasks and similar items behind an Archive/Unarchive action. Archived items come back via search or a "Show archived" toggle. |
| **Trash** | Deleted items are not gone right away. Projects, threads, tasks, vision documents, and agent templates move to a recoverable deleted state first — each area has its own restore view — before a scheduled purge removes them for good. |
