## Chain Projects

A **chain** links several projects together and runs them one after another under a single overarching goal. It is the tool for work that is too big for one project but has a natural order — for example, scaffold a service, then build the feature on top of it, then add tests. A chain coordinates your own projects; it is not a shared-team feature.

Each project in a chain keeps its own description, agents, and 360 Memory entry. What the chain adds is a coordinator that launches them in order so you do not have to start each one by hand.

### Linking Projects

Linking is the act of attaching projects together into a chain.

1. Go to **Projects** in the left navigation.
2. Click the chain-link button in the toolbar (**"Link projects (chain mode)"**). A **Linked** checkbox column appears in the project table.
3. Tick the projects you want in the chain. A chain holds **2 to 5 projects** — a hint appears if you have selected too few or too many.

The order you want the projects to run in is the order they carry in the table. Projects already locked into a running chain are shown as unavailable so you cannot double-book them.

### Launching a Chain

Once you have linked 2 to 5 projects, an action bar appears at the top of the project list with a launch button labeled **"Run sequential (N/5)"**, where N is how many projects you currently have linked.

Clicking it does not run the chain by itself — the dashboard cannot spawn agents. It queues the linked projects as a pending run. From there, an agent connected through your AI coding tool picks up that pending run and becomes the **conductor**, which does the actual work: staging the first project, then launching, watching, and advancing through the rest in order.

After the conductor stages the first project, it pauses and waits for your explicit go-ahead before starting implementation — the same human-in-the-loop checkpoint a solo project has, just at the head of the chain. Between projects, each finished project gets its own Review step: its card in the chain's group on the **Jobs** board shows a **Review** link, and you review and close it out from there.

### The Conductor

The **conductor** — also called the chain orchestrator or master orchestrator — is the coordinator that drives the chain. It is a dedicated agent that owns no project of its own; its only job is to run the chain in order: launch each project, watch for completion, and advance to the next. You follow its progress in the chain's group on the **Jobs** board: the step counter and the lit card show where it is.

### The Chain Mission

The **chain mission** is the overarching goal for the whole chain — the single objective that all the linked projects serve together. It is distinct from each project's own per-project mission. It appears in the header of the chain's group on the **Jobs** board, labeled **"Chain goal"** and tagged **"Conductor Generated"** once the conductor has written it.

### Monitoring a Chain

On the **Jobs** board a chain is one group. Its header shows the chain's name, a **Step n of N** counter, the execution mode and the chain goal, with the chain's controls: **Stage Chain** (or **Unstage Chain**), **Implement** to start the whole chain, **Copy master prompt** for a multi-terminal chain, **Stop chain** while it runs, and **Deactivate chain**. Below the header each project in the chain has its card, in run order and numbered by step. Only the step that is running is lit; finished steps and steps still waiting are dimmed. Each card works like any other card on the board: agent rows, the play button, messages and **Jobs detail**. A card also offers a fallback prompt that runs just that one project, while the conductor still decides what comes next.

A project that belongs to a chain lives only in its chain's group; an older link to it opens the Jobs board.

### Stopping a Chain

To end a running chain and keep the work already done, use **Stop chain** in the chain's header on the **Jobs** board. To return its projects to their prior state, use **Deactivate chain**, either in that header or from a project's action menu on the Projects page. This rewinds all linked projects out of the run; you can re-link and relaunch when you are ready. Completed projects keep their results and 360 Memory entries.

For guidance on *whether* a chain is the right choice versus a single project, see **When to Use What**.
