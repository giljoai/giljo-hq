## When to Use What

Giljo HQ gives you a few choices when you start work. This chapter helps you pick the right one each time. None of these decisions are permanent — you can capture a task now and run it as a project later, or start with one project and link more into a chain when the scope grows.

### Project or Task?

A **task** and a **project** are different kinds of work item.

- A **task** is a note: work you have identified but not yet scheduled. Tasks live on the Tasks & Handovers board, cost nothing to create, and are ideal for capturing ideas, technical debt, and follow-ups mid-session. A task does not run agents on its own.
- A **project** is work you actually run. It has a description, an agent team, a mission, and a closeout that writes a 360 Memory entry. Create a project when you are ready to build something.

| Use a task when… | Use a project when… |
|---|---|
| You want to jot down work for later | You want agents to do the work now |
| The item is a single step or a reminder | The work has multiple steps or phases |
| You are capturing debt or an idea mid-flow | You have a clear goal and want a plan |
| You do not need a plan or agents yet | You want a 360 Memory entry at the end |

Start with a task when in doubt — it is the cheaper choice. If you have not decided on a task yet, set it to **On hold**: it stays on the board as open work, and unlike **In Progress** it does not record a start time. When a task is ready to become real work, open it and choose **Convert to Project**. That creates a new inactive project from the task without disturbing whatever project is currently active; you activate the new one yourself when you are ready.

### Handovers

A **handover** is the third kind of item on that board, and it answers a different
question: not "what should we do" but "where did we stop, and what of this can you
trust". Write one when a session ends with work still in flight.

Because the person reading it cannot ask you anything, a handover has to carry three
sections, and the board will not accept one that does not:

- **Verify before trusting** — every claim next to the command that checks it. Not
  "the tests pass", but the command to run and what a passing run prints.
- **Waiting on the operator** — anything that needs you before it can move.
- **Cannot testify** — what the author did not verify. This is the section that makes
  the other two believable.

Its status means something slightly different from a task's: **Pending** is written
but unread, **In Progress** means someone is checking it, **Completed** means verified
rather than merely read, and **Blocked** means a claim turned out to be false and needs
you. A handover is a record, so it is never converted into a project, and one nobody
has read yet cannot be archived out of the list.

You can create either from your AI coding tool with `/giljo` — for example, `/giljo add a task for the three things we just discussed` or `/giljo add a project for the authentication gaps`.

### Execution Mode: Multi-Terminal or Subagent?

When you stage a project, you choose how its agents run.

- **Multi-Terminal.** Each agent gets its own prompt, and you run each one in a separate terminal window. You are in control of launching and watching each agent. This suits workflows where you want to supervise agents individually or run them on different machines.
- **Subagent.** One main agent connects, then spawns its subagents inside a single session. You launch once and the orchestrator manages the rest. This works with Claude Code, Codex CLI, OpenCode, and any MCP-enabled tool that supports subagents.

| | Multi-Terminal | Subagent |
|---|---|---|
| Terminals you open | One per agent | One |
| Who launches each agent | You | The orchestrator |
| Best for | Hands-on supervision, agents across machines | A single guided session |

In multi-terminal mode, phases run one after another and the agents within a phase run in parallel. In subagent mode, the orchestrator spawns its agents together and coordinates them directly; once your tool connects, a read-only **"detected: {tool}"** chip confirms which harness GiljoAI recognized. How often a waiting agent checks in for new work is one account setting, **Check-in cadence**, under **Tools > Agents**; it applies in both modes.

### One Project or a Chain?

Most work is a single project. Reach for a **chain** when several related projects should run one after another toward one overarching goal — for example, a scaffolding project, then the feature that builds on it, then a hardening pass.

- **One project** when the work is self-contained and finishes in a single run.
- **A chain** when the work spans multiple projects with a natural order, and you want one coordinator to run them one after another without you launching each project by hand.

A chain links 2 to 10 projects and runs them under a dedicated coordinator called the **conductor**. See the **Chain Projects** chapter for how to link projects, launch a chain, and monitor it.

### Roadmap or Projects List?

Both surfaces work with your product's projects, but for different jobs.

- The **Roadmap** is a ranked queue your AI agent maintains for you: it scores your inactive projects and pending tasks by risk and complexity so you know what to tackle next. Reach for it when you want your agent's opinion on what comes first.
- The **Projects list** is where you manage everything directly: create, edit, activate a project, link projects into a chain, or close one out. Reach for it when you already know what you want to do.

Activating a project from either place takes you to the same project workspace.
