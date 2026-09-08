# Changelog

All notable changes to this project are recorded here. This changelog follows the [Keep a Changelog](https://keepachangelog.com/) convention — entries are grouped by change type (Added / Changed / Fixed / Removed / Security). Versions follow `MAJOR.MINOR.PATCH[.HOTFIX]` and tags live on the public repository (`giljoai/giljo-hq`).

## [2.1.0] — 2026-09-06

### Highlights

- **Work several products at once.** The dashboard is now product-tabbed, and every agent tool can name the product it means — no more silent guessing when you have more than one.
- **Run the whole project lifecycle from your coding agent.** Stage, launch with a goal, answer approvals, un-stage, supersede, revive — the dashboard lights up live while you stay in the terminal.
- **One notification model.** Banners ask, pop-outs echo when you're away, toasts confirm your own clicks, and the bell remembers everything — with browser pop-ups that now request permission properly.
- **A connect wizard that tells the truth.** Tool cards flip green the moment your tool really connects, "Remove tool" really forgets it, and reconnecting verifies this machine — plus OpenCode joins the supported tools.
- 73 fixes across onboarding, the message hub, billing surfaces, and agent plumbing.

### Added

- **A superseded project says what replaced it.** Opening one now shows the
  project it was replaced by, as a link straight to it.
- **List, roadmap, and memory-search tools can now target a specific product.** `list_projects`, `list_tasks`, `get_roadmap`, `update_roadmap_metadata`, and `search_memory` accept an optional product to read from or write to, so an agent working across several products no longer has to worry about another session (or you, in the dashboard) switching the active product out from under it mid-task. Leaving it out works exactly as before.
- A headless agent can now end a linked-project run early (freeing its remaining
  projects) and mark a finished project reviewed, without needing the dashboard.
- Your connected coding agent can now list your products by name — useful when it needs to figure out which product an instruction like "work on Yapper" refers to before it can act.
- **Setup can now bind a repository to a Giljo HQ product.** Running setup
  with a product id writes a short marker into your project's CLAUDE.md and
  AGENTS.md, so future actions in that repository know which product they
  belong to and stop asking. If you have exactly one product it binds
  automatically; with several, you'll be asked to confirm which one.
- **Your coding agent can now un-stage, re-stage, or cancel staging on a project**, and revive a completed project to work on it again — no need to switch to the dashboard for these.
- **Your coding agent can now mark a project as superseded and point it at the project that replaced it**, matching what's already possible from the dashboard.
- **State your goal and say go, in one call.** Launching implementation from your coding agent now accepts an optional goal — no separate step needed to set it first.
- **Multi-terminal agents can now get their startup instructions inline** from your coding agent instead of always pointing you back to the dashboard's Copy button.
- **Answer your agent's pending question without leaving the terminal.** When an
  agent asks for a decision, you can now reply directly from your coding agent
  session instead of switching to the dashboard to click a button. The dashboard's
  approval card still works exactly as before.
- **Switch, activate, or deactivate products from your coding agent.** `update_product_context` now takes an optional activation flag, so an agent can switch which product it's working on -- or correct a product's platforms, custom extraction instructions, and other fields -- without you clicking through the dashboard first.
- **Rename a chat thread while posting to it.** Posting a message can now rename the thread in the same step, matching the rename button already in the dashboard.
- **Approval audit rows now record whether a human or an agent made the decision.** Answering a pending approval from the terminal (MCP) used to leave the "decided by" field completely blank; it now records the channel (dashboard or terminal) alongside the decision, so the history is honest instead of silent.
- **Open more than one product at a time.** The dashboard now shows a tab
  strip for every open product — switch between them without losing your
  place, and create, edit, or browse projects in one product without
  touching another.
- **Background product tabs now show a live badge when something happens there.** With multiple products open in tabs, an agent working on a product you're not currently viewing now shows a small counter on that tab instead of being invisible until you switch to it.
- **New here? The setup wizard and tutorial now show you both ways to work.** Once you finish setup, one of the launch cards points you at driving projects from your terminal instead of the dashboard. Activating your first product in the tutorial also mentions that your connected agent can do that step for you. Neither replaces the other, and you can mix and match any time.
- **The in-app guide now has a chapter on driving everything from your terminal**, covering products, project staging, and chains, right alongside the dashboard steps for each.
- **Product cards now have a Default control.** Check the box on any product
  card to choose where reads go when nothing else is specified (agents must
  still always name a product when writing). Exactly one product can be the
  default at a time, and it can be a hidden product too.
- **See agent activity and questions from anywhere in the app, not just the project you have open.** The "Projects" tab in the sidebar now shows a badge when an agent starts working, changes status, or makes progress on a project you're not currently viewing. When an agent needs a decision from you, a banner now appears on every page — not only when you happen to be looking at that project — so a headless drive never goes silent just because you clicked away.
- **A banner now tells you when an agent has named you or asked you something in a
  chat thread.** It appears wherever you are in the app, says which chats are
  waiting, and clears itself when you read the thread. Desktop notifications for
  those messages now follow the banner too, so they disappear once you have looked
  instead of lingering and sending you to a message you already handled.

### Changed

- **Activating a project that lost a race against another activation in the same product now returns a clear "another project is already active" message instead of a generic retry error.**
- **Creating a project or task without naming a product now asks instead of guessing, once you have more than one product.** Before, a bare create silently landed on whichever product happened to be active — easy to get wrong if you (or another session) had switched tabs. Now it tells you every product you have and asks you to pick. If you only have one product, nothing changes.
- You can now work on several projects at once inside a single product — activating one no longer pauses another.
- **Launching and approving work from a connected coding agent is now available.** Whether a connected agent may do this is controlled under Settings → Security.
- Tool names are now final. The temporary older names that were kept working for one release have been removed, and two more tools are named for what they do: closing out an agent's finished work is now called finalizing it, and fetching a product's vision document uses the full word. Existing sessions keep working until they are restarted; start a new session after updating to see the current tool names.
- Trimmed the instructions your AI agents read before every action. A note about choosing between message hubs was being repeated on fifteen separate tools, including four that have nothing to do with messaging, when the same note is already delivered once when an agent connects. Guidance about paging through long lists was being explained three times per tool, and the same paragraph about which product to work on appeared four times in four slightly different wordings. The staging tool now offers only the two choices that still mean anything instead of six, four of which it then argued against. Nothing an agent could do before has changed; there is simply less to read first.
- Two pairs of tools that asked the same question in two ways are now one tool each. Waiting for your turn in a conversation is no longer a separate tool from checking whose turn it is, and searching your chats is no longer separate from listing them. Your agents keep working either way: the old names still respond for now and point at the replacement, so nothing you have already connected breaks.
- Running several projects back to back is now two plainly named tools instead of one tool with a hidden list of actions. Your agent links the projects it wants to run in order, and later unlinks them if the plan changes. Each project still hands off to the next on its own once it is finished, so there is nothing to drive by hand in between. The old tool name still answers for now and points at the replacements, so anything you have already connected keeps working.
- The tool that fetches a project's implementation prompt is now called what it does. It was named as though it started the work, sitting beside another tool with a nearly identical name, and neither of them actually ran anything. Your agents keep working either way: the old name still answers and points at the new one.
- Three tools are now named after what they do. Saving your roadmap was called updating roadmap metadata, which made it sound like it changed notes about the roadmap rather than the roadmap itself. The old names still answer for now and point at the new ones, so anything you have already connected keeps working.
- **Connecting a tool now confirms the connection you just made.** When you start a
  connect flow, the tool shows as waiting until it connects to this machine, instead
  of appearing already connected because you set it up somewhere else earlier. Your
  tool list still remembers what you have configured, as before.
- In-app copy and the AI agent guide now describe working on several products at once, instead of talking about a single active product you have to switch between.
- **The "an agent needs you" banner now shows plain, fixed status text and a project tag instead of freeform wording.** It used to always say the same generic line; it now tells you at a glance whether a project is waiting at staging, an agent is blocked, or a decision is needed, and tags each with its project so you can tell them apart before opening Review.
- **Products are now Show/Hide, not Activate/Deactivate.** Every product can
  be shown as a tab at the same time — hiding one never pauses its projects
  or agent jobs, and showing a new one never hides another. New products are
  shown by default.
- With more than one project active at once, Jobs now opens a sectioned overview showing every in-flight project instead of picking one at random.
- The Projects list no longer greys out a project's Activate button just because another project happens to be active.
- **The Message Hub is now one space instead of a per-product view.** Every thread you can reach is listed together, with a filter defaulting to the product you're viewing so the everyday view looks the same as before. Switch to "All products" to see everything, or "No product" to find older threads that were never tagged with one.
- **New threads are tagged with a product automatically** when one can be figured out, so they always show up in the right place. You can also tag (or retag) any thread's product and projects at any time, including older threads that predate this change.
- **The Jobs board now matches the rest of the product.** Cards use the same
  colors, badges, and status pills as everywhere else, show each agent's
  progress and duration at a glance, and explain why a project is waiting for
  you when it's paused for your go-ahead.
- **Banners no longer stack.** When more than one notice is waiting at the top of the app, they now fold into a single strip with a count badge and a chevron to expand the full list, instead of piling up as separate bars across the top of the page.
- **The Roadmap page now focuses purely on ordering your work.** Drag-to-reorder, converting a task to a project, and removing an item are still all there. Launching or managing a chained run has moved to the Projects page and your connected agent — the Roadmap is where you plan the order, not where you start the work.
- **Each kind of notification now has one job, so nothing announces itself twice.** When an agent hands you a baton, mentions you, or needs a decision, you get one notification instead of a pop-up and a toast at the same moment. The desktop pop-up and the bell entry both stay.
- **Desktop pop-ups only appear when the app is hidden.** Previously a pop-up could fire at a window you were already looking at. If the app is in front of you, the title-bar banner tells you on its own.
- **A desktop pop-up now goes away when the thing it was announcing is handled.** Answer a baton and its pop-up closes with it, so you can no longer click a notification for something you already dealt with. Repeats of the same signal replace the earlier pop-up rather than stacking up.
- **The bell is quiet.** It keeps a count of what you have not seen and no longer pulses red or amber. Anything genuinely waiting on you appears as a banner, which is the one place urgent things live.
- **Connection problems now show on the connection indicator instead of the bell.** Losing the server no longer drops entries into your notification list or raises a toast; the indicator beside the bell shows the current state, which stays accurate as it changes.
- Staging now asks how you want a run to work instead of quietly choosing for you. When you drive a project from your coding agent and do not say which way the work should run, staging comes back with both options and their plain-language difference so the agent can put the question to you. If you always want the same answer, set it once under Tools then Agents and you will not be asked again.
- **A request for action addressed to everyone no longer interrupts you personally.**
  It still appears in your notification bell, but it no longer raises a banner or a
  desktop notification claiming you specifically owe an answer, because that kind of
  request is for whoever picks it up.

### Fixed

- **Every notice at the top of the screen can now be closed.** The raised-hand,
  chat-mention and "waiting on you" strips each have a dismiss X, and closing
  one stays closed after a reload. Closing a notice only hides the
  announcement — the decision, the mention or the handover is still waiting for
  you in the Message Hub and the bell.
- **The "you were mentioned" notice no longer sticks around forever.** When
  several threads named you, its button went to the Message Hub without marking
  anything read, so the notice could never clear itself. Pressing that button
  now **marks every thread the notice names as read, including ones you do not
  open** — that is what lets the notice clear. The messages themselves are not
  touched and are still there in the Message Hub. If you would rather not mark
  them, use the dismiss X instead: it only closes the notice and marks nothing.
- **Browser pop-ups can now actually be turned on.** The settings card said your
  browser would ask for permission the first time something needed to reach you
  — but it never could, so anyone who left the pop-up setting on its default
  never got asked and never saw a pop-up. There is now a **Turn on pop-ups**
  button that asks straight away, and the card says plainly that nothing pops up
  until you use it.
- **Usage metrics no longer occasionally fail to save.** A rare timing issue could cause one server process to briefly fail while recording API and MCP usage counts when another process was doing the same thing at the same moment. Both now save in a consistent order, so this contention can no longer happen.
- **A project activation that got superseded by a competing activation could report success even though the project stayed inactive.** Racing another activation for the same product now always tells you clearly when yours lost, instead of sometimes claiming it worked.
- Tool descriptions for creating projects and tasks now explain what actually happens when you own more than one product and skip naming one: the call is refused with a clear list of your products to choose from, instead of silently guessing.
- The launch-implementation tool description no longer implies it only works from a command-line session — it works from any connected chat client, and clearly states that launching does not activate the project (a separate step).
- The staging and implement tools now describe both ways to release the implementation gate, not just the dashboard button.
- Starting a chain run now documents that a project finished by a hands-off run automatically satisfies its review step, so nothing gets stuck waiting on a click that will never come.
- The setup tool now states plainly that outdated skills are only ever flagged for you to refresh yourself — never rewritten automatically.
- **Activating a project in one product no longer greys out the Activate button in another product.** With multiple products open in tabs, an active project in Product A was incorrectly treated as "the" active project everywhere, blocking activation in every other product.
- The notification bell no longer leaves stale entries behind after you finish a project; clearing project notifications now catches every notification shape, not just some of them.
- When several products exist and an agent creates something without saying which one, the message explaining what to do is now clean. It previously had internal diagnostic details appended to the end.
- Deleted agent templates that a product had in use are now cleaned up properly instead of being left behind forever. The background tidy-up job also no longer stops early when it hits a single problem row.
- Launching a project from your AI tool now tells you when the project still needs activating, instead of reporting success while the dashboard shows nothing.
- Completing a project (or pressing Archive) no longer silently skips its closeout record when there's still unresolved work, such as an unread decision waiting on you. The harness now asks you to finish closing out first, or to explicitly confirm you want to abandon it anyway.
- **A chain run driven entirely by a CLI agent no longer disappears from the dashboard's review view with a burst of errors.** Headless completion now counts as your per-card review, and an open chain view now shows a clean "this chain has finished" message instead.
- Launching implementation now always returns a readable timestamp, whether the project was just launched or was already launched, so an agent checking either timestamp field no longer sees a false failure.
- A project whose agent has finished and closed out no longer shows as 0% progress with an unknown stage; closed agents now count toward completion.
- **Your AI agent gets clearer, more accurate instructions when it connects.** The
  built-in routing guide no longer sends closeout steps in a duplicated, contradictory
  order (which could double-write project history), and now correctly explains when a
  project needs a product ID, how to permanently link a repo to one, and how to recover
  from a blocked archive attempt.
- Corrected tool instructions that told your AI agents the wrong thing. Agents were being told that only one product could be open at a time and that opening one would switch their working context, which stopped being true when several products could be shown at once. They were also told that answering an approval from the terminal needed a setting turned on, when it is on by default. Error messages that appeared when an agent did not name a product now point at something the agent can actually do, instead of suggesting a step that would fail again. The most consequential settings on the project tools are now described and offer their valid choices up front, so an agent picks correctly the first time rather than guessing.
- **Agent template downloads now follow the right product.** If your account
  has more than one product, running setup (or downloading agent templates)
  could sometimes install the wrong product's agents instead of the one you
  meant. Downloads now always match the product you're working in.
- **A single long-running request could no longer slow down everyone else's dashboard.** Server requests are now automatically stopped if they run far longer than expected, so one stuck request can't tie up the connections other people's requests need.
- **Replying in the Message Hub now clears your "waiting on you" banner.** A
  dashboard reply used to leave the banner up even after you answered, forcing
  a manual click on the raised-hand button to dismiss it. Now, answering a
  thread you hold the turn on clears it automatically: a direct reply hands
  the turn to whoever you addressed, and a plain reply marks it answered for
  everyone.
- Every tool now carries its display name in both of the fields the MCP standard defines for it, so connector directories and other clients that read the older field see a proper name instead of blank.
- The tools reference now matches the tools the server actually registers: entries renamed last release point at their current names, two tools that were never listed are documented, and the counts are correct again.
- **Agents are no longer told to call tools that were renamed.** The startup
  instructions every orchestrator loads, and a number of on-screen hints, still
  named a handful of older tool names. Agents following them would look for a
  tool that no longer exists and only discover the gap when finishing their
  work. Every instruction now names the current tool — and where the rename
  also changed how a tool is called, the instruction says so, so an agent
  waiting for its turn genuinely waits instead of checking in a loop.
- **The "GiljoAI updated its tools" notice on a fresh install now points at
  tools that exist.** Two of the eight renames it listed had themselves been
  superseded since the notice was written, so anyone following those two rows
  went looking for something that had been removed.
- **The tool guide now counts its own chat tools correctly.** It announced eleven
  and then listed nine — the other two had been folded into the tools beside them
  in an earlier release, and the sentence introducing the list was never updated.
- **Agents downloaded for Gemini CLI can now use every connected tool.** Previously, agents exported for Gemini CLI carried a fixed, outdated list of allowed tools that matched none of the currently connected tools, so a downloaded agent could not call any of them. Gemini agents now automatically get access to every connected tool, the same way agents exported for other coding assistants already do.
- Setup wizard: connecting a **second** coding tool is now detected. The Connect step used to sit on "Waiting for ... to connect" forever if you had already connected any tool before, even though the new tool was working perfectly. The same fix means re-running setup with a tool you already have now flips it green again.
- **Activating a project from your coding agent now deactivates the other active project for that product, instead of failing.** Previously this only worked from the dashboard.
- Setup now installs agent templates for OpenCode. Picking OpenCode in the connect wizard previously left you with manual download steps and no agents, because setup did not recognise it as an install target.
- **Series-number checks no longer look across products when nothing is active.** With no active product selected, checking whether a series number was available, listing used series numbers, or listing used subseries could previously report results based on projects in a *different* product. All four checks now agree and stay scoped correctly.
- A chain project's coordination hub thread now always shows up under the right product, even when the chain conductor creates it directly instead of through the app's own prompts.
- When an agent template is set to run under opencode, the multi-terminal launch
  command now starts opencode the way opencode expects, so that agent's terminal
  boots with its mission instead of opening an empty session. Templates set to
  Claude, Codex, Gemini or Antigravity are unchanged.
- **Your connected tools show up again on the Connect page and in setup.** Newer
  versions of coding tools greet the server a different way than they used to, and
  that greeting was not being recorded, so the dashboard could not tell which tools
  were attached even though they were working normally. The server now recognises
  both greetings. Nothing about how tools connect or behave changes.
- **Setup now asks which product to install agents for, instead of picking one.** If
  you have more than one product, running setup without naming one used to quietly
  package a product's agents and only mention the ambiguity afterwards. It now stops
  and lists your products so you can choose. Nothing is downloaded until you have.
  If you have a single product, setup binds to it without asking, exactly as before.
- **The setup wizard now notices your tool connecting, without a refresh.** Newer
  coding tools greet the server a different way, and the wizard was only listening
  for the older greeting, so "waiting for connection" sat there until you reloaded
  the page. It now hears both.
- **"Remove tool" now actually forgets the tool.** Removing a tool used to leave its
  connection on record, so adding it back showed it connected again from history. It
  is now properly forgotten and the card returns to waiting.
- **Pages load lighter after the first visit.** Logos and icons are now cached
  by your browser for a day instead of being re-checked on every single page
  you open, so moving around the app takes fewer requests and feels quicker.
- **Deleting an account no longer leaves usage counts behind.** Usage totals are
  written in batches every few minutes, and a batch already in flight could
  write a deleted account's row back into the table minutes after erasure.
  Batches now skip accounts that no longer exist.
- Removed two stale exemptions from the edition-placement check so it now covers the files it was added for, and made the check impossible to call in a way that silently reports a file as clean without reading it.
- **Staging and launch now update the Projects list and Roadmap live, even when driven from your coding agent.** Previously those screens only refreshed when a project's own tab was open, or after a manual page reload. A newly started multi-project conductor also now appears live instead of waiting for a refresh.
- **Opening a product in one browser tab no longer switches what another tab
  is showing.** A background sync used to silently jump you to whichever
  product had just been opened elsewhere — now it only refreshes the status
  indicator, and the tab you're looking at stays put.
- **The "Projects" sidebar badge no longer counts activity from other products.** It previously summed activity across every open product, so switching to Product A could show a badge count that only made sense for Product B. It now only counts what's actually in the list you're looking at.
- **The Message Hub now shows only the threads for the product tab you're viewing.** Switching product tabs used to leave the Hub showing every product's threads mixed together; it now follows the tab the same way Projects and Tasks already did.
- **The product-refresh network call no longer fires repeatedly on page
  load.** Several parts of the app used to ask the server the same question
  in a burst; they now share one answer.
- **The Jobs pane now notices a project going live without a page reload.** When a project is activated from another window or driven headlessly, the pane updates in place instead of leaving you staring at a stale "No Active Project" screen until you refresh.
- **The quick-launch card grids on the Welcome and Tools pages no longer collapse to a single narrow column on tablets.** A two-column layout now fills the tablet width band that used to jump straight from three columns to one.
- A banner now announces at the top of the page when a project is staged, activated, or starts implementation from either the dashboard or your coding agent, with a button straight to that project's jobs view.
- Clicking the "waiting on your decision" banner now takes you to the actual decision screen, even if you weren't already on that project's page.
- The chain conductor's empty mission placeholder no longer renders half cut off.
- The Jobs view now shows each running project's details again. Cards were appearing
empty, with no project name, status, or agent names.
- **"Needs your approval" notifications now only fire when it's actually your approval.** Previously, any agent-to-agent request sent through the Hub could pop a "Needs your approval" alert for you even when it was addressed to a different agent. Those notifications are now filtered to the ones actually meant for you.
- **The sign-in page no longer tells a throttled user their password is wrong.** If you sign in too many times in a short window, the login screen now says you're signing in too fast and to wait a minute, instead of the misleading "check your credentials" message.
- The Jobs board no longer tells you that headless mode is off when it is on. The
notice on a waiting project now reflects your actual setting.
- The Jobs detail window no longer says a project's agents are all finished when
they are still running.
- The Jobs board no longer mislabels a newly activated project as "Staged" -- it now shows an honest Activated status until staging actually begins, with its own filter and a Planning status for projects that are mid-staging.
- The Jobs board's header, agent badges, and message counters now match the rest of the app's look and feel.
- Sign-in failures now explain what actually happened. A wrong password, an inactive account, a blocked account, a rate limit, and a network problem each show their own message instead of one generic "check your credentials" line.
- The dashboard's copy-prompt buttons now hand your agent commands it can
  actually run. After the tool renames in the last release, the Roadmap page
  and the vision-analysis step were still producing prompts that named tools
  the server no longer answers to, so pasting one got you "tool not found".
- The Roadmap prompts now name the product you are looking at. Previously, on
  an account with more than one product, the agent had to guess which roadmap
  to save — and the save could be refused outright at the last step.
- **The onboarding wizard's connect and install checkmarks no longer get stuck.** If your coding tool was already connected, the Connect step now shows it as connected right away instead of waiting forever. The Install step's checkmarks now reliably tick after running the setup command, even if you reload the page or come back to a setup you started earlier.
- **The "waiting for your agent" indicator is easier to see** while your agent works on your product proposal.
- **Fixed wrong on-screen instructions** that asked you to come back later. The screen now correctly tells you it will refresh itself.
- **"Activate product" is gone.** Reviewing your agent's proposal now ends with a simple "Done!" button, and the screen updates live if your agent revises the proposal while you're looking at it.
- **The finish screen now describes what you'll actually see** on your Home screen next, instead of a placeholder that didn't match.
- **Product cards on the Products page no longer clip or misalign.** The
  "Completed" stat no longer splits across two lines, the Default checkbox's
  label is fully visible instead of being cut short, the Delete button no
  longer renders as a barely-visible sliver at the card's edge, action
  buttons now stay aligned along the bottom of every card regardless of how
  much content it has, and long product names no longer overlap the "Shown"
  badge.
- Opening the app no longer sends you back to the sign-in screen while your session is still valid. If the network hiccupped for a moment during start-up, the app treated it as a sign-out and returned you to the login page. It now keeps the session it has already confirmed and checks again on your next move.
- The onboarding review screen now shows your agent's full product proposal. The description is no longer cut short, and architecture, standards, testing, and the complete tech stack are all on screen before you activate, with anything your agent left empty clearly marked instead of hidden.
- Setup wizard: the "Install skills & agents" step now keeps **Next** switched off until both the skills and the agent templates have actually arrived. It no longer assumes they are there because you ran setup once before, and it no longer counts skills on their own as finished. "Skip, I'll do this later" is still there if you would rather move on.
- Setup wizard: a switched-off **Next** button now looks switched off. It used to keep its bright yellow fill, which read as clickable.
- Your Connect page now shows which tools are actually connected. Previously, connecting a single tool turned every tool green, including ones you had never set up on that machine.
- **The Tasks list no longer resets your filters every time an agent updates a task.** Your search, status, and priority filters now stay put while agents work in the background.
- **The Dashboard, Memory Browser, and Products pages now update live.** Stat tiles, recent activity, 360 memory entries, and product cards refresh automatically as your agents work — no more waiting for a page reload to see the latest state.
- **Answered questions and cleared alerts now disappear on their own.** Status
  banners used to stay on screen after the thing they were telling you about
  was already resolved — you had to reload the page to make them go away.
  They now clear themselves the moment the condition clears.
- **The "tools were renamed" notice now actually shows up.** A one-time
  heads-up about renamed commands was being created but never displayed —
  it now appears for self-hosted admins during the first few restarts after
  an update.
- **Superseded projects now get their own badge colour**, instead of looking identical to inactive projects.
- **The "Mark Superseded" successor picker now shows each project's ID** alongside its name, so you can tell candidates apart at a glance.
- **Not-yet-started projects can now be picked as a successor** when marking a project superseded — previously only active or completed projects were offered.
- **Deleting a project now removes it from the Projects list immediately.** Previously a deleted project could keep showing in the list (with a red "Deleted" label) until the page was refreshed. It now leaves right away and shows up in the trash, where it can still be restored.
- **The guided tour no longer goes quiet if a document upload cannot be attached to a product.** Previously the tour could sit on the upload step as though nothing had happened, while a product had in fact already been created and named after your file, leaving you with something you did not ask for and a tour that looked broken. It now tells you what happened, and says specifically whether a product was created, so you know whether trying again would make a second one.
- **The guided tour now offers a way forward when a document upload cannot start.** If the product could not be created — because the server was busy, your session had expired, or the request was rate-limited — the tour used to stop with no way to continue. It now explains what happened in terms of that actual reason, offers **Try again** when nothing was created so retrying is safe, and always offers **Fill it in myself instead** so a failure is never a dead end. When something *was* created but the file could not be attached to it, the retry button is withheld on purpose and the message says so, because trying again in that case would leave you with a second product named after the same file.
- **Your browser is now actually asked for permission to show pop-up notifications.** Before this, the request could only happen while the app was hidden in a background tab — which browsers ignore — so on a new machine or profile the prompt never appeared and pop-ups could never work at all, no matter how long you used the app. Turning pop-ups on in Settings now asks straight away, and the card tells you what your browser answered: allowed, blocked, or not yet asked. Choosing "Nothing" still never asks. If your browser says no, your choice is still saved, because it follows you to your other machines.
- The onboarding tour's "I have an existing codebase" step now tells you when it
  could not set up your product card, and offers a Try again button, instead of
  leaving you on a prompt that quietly had nothing behind it.
- That step also stops offering its prompt for copying until your product card
  actually exists, so you can no longer hand your agent a prompt pointing at
  nothing.
- Returning to that step now reuses the blank product card it made for you last
  time instead of trying to make a second one and failing, so the tour keeps
  working if you come back to it.
- Leaving the tour part-way no longer strands the blank product card it created
  behind, so your product list stays clean.
- **Threads you have read no longer keep saying they have something new.** Opening a
  thread now records that you read it, so its card stops showing the unread marker.
  Before this, the marker stayed on for good once anyone posted, because nothing on
  the dashboard ever told the server you had looked.
- **Being mentioned in a long message no longer goes unnoticed.** Whether you were
  named used to be worked out in your browser from a shortened copy of the message,
  so a mention written near the end of a long post could be missed entirely. The
  check now happens on the server against the whole message.
- **Requests an agent sends to the whole thread no longer disappear.** They now show
  up in your notification bell, listed as an open ask, so you can find them later.
  They still do not raise a banner or a desktop notification, because that kind of
  request is not addressed to you in particular. A request aimed at you directly is
  unchanged and still gets your full attention.
- **You can create Message Hub threads again when you have more than one product.** The New Thread dialog was not telling the server which product the thread belonged to, so once you owned a second product the server could no longer tell which one you meant and refused to create anything. The dialog now uses the product whose tab you are viewing, and simply creates a standalone thread if you have no products yet.
- Connection commands shown during onboarding and under Tools now work in every terminal, including the default Windows PowerShell. Multi-step commands are listed one per line instead of being chained together in a form some shells reject.
- **A filtered thread read no longer claims to mark messages you had already marked.**
  Reading a thread with a filter — only action-required posts, only posts addressed to
  you, or only the last few — still marks exactly those posts as read, but it cannot
  move your "read up to here" marker, so the same posts keep coming back. The count now
  reflects only what actually changed, and the reply says the marker did not move and
  which read moves it.
- **A blocked job completion now tells you where the blocking messages are.** When
  unread action-required messages stop a job from completing, the message names the
  thread they are on — which is not always the thread you have been working in — and
  the exact unfiltered read that clears the block.
- **Giljo HQ no longer risks exhausting its own database under a traffic burst.**
  The server now opens far fewer database connections by default, so a busy moment
  can no longer use up every connection slot and start refusing new ones across the
  whole app.
- **Self-hosted installs keep ample room.** A single-user install still gets ten
  concurrent database sessions, comfortably inside a stock PostgreSQL. If you had
  already tuned the pool yourself with `GILJO_PG_POOL_SIZE` or
  `GILJO_PG_MAX_OVERFLOW`, your own settings still take precedence.
- **The MCP server's health check now reports its current name.** `health_check` was still
  reporting the retired `giljo_mcp` server identifier after the Giljo HQ rename; it now
  reports `giljo_hq`, matching what agents actually connect to.
- **New accounts can now finish setup even if a trial lapses first.** If you signed up but hadn't finished setting up your workspace when your trial ended, "Complete Setup" used to do nothing and leave you stuck. Setup now always completes, and you land in your workspace with a reminder to reactivate your subscription.
- **Startup no longer fails when several server workers start at once.** A
  startup race could leave concurrent server workers using inconsistent
  encryption keys, and a worker that ended up with an unusable one stopped with
  an unhelpful message. Workers now agree on a single key, and a key file that
  really is unusable says which file it is and what to do about it.
- **A mistyped encryption key is reported by name.** Setting
  `GILJO_MCP_ENCRYPTION_KEY` to a value that is not a valid key now says exactly
  which setting is wrong and how to generate a correct one, instead of failing
  with a bare cryptography error.
- **The encrypted secrets store no longer breaks when several processes start
  it at once.** With no master key configured in the environment, concurrent
  processes could end up disagreeing about which key to use. There is now a
  single agreed key, and a key file that really is unusable says which file it
  is and what to do about it.
- **A mistyped secrets key is reported by name.** Setting `GILJO_SECRETS_KEY`
  to a value that is not a valid key now says exactly which setting is wrong
  and how to generate a correct one, instead of failing with a bare
  cryptography error.

### Security

- **Closed a self-declaration gap in how a connected AI client's capability level is determined**, so that value can no longer be used to reach a privileged action — only your own account settings can grant that now.

### Removed

- **Removed an unused "switching products" warning dialog** that no longer
  matched how multiple products can be shown at once.

## [2.0.4] — 2026-08-21

### Highlights

- **Messages to finished agents no longer pile up.** A note sent to an agent that had already finished used to sit forever as unread, on a job that will never read it. Those badges stay accurate now, and you are told when a message could not be delivered.
- **Agents stay attached to a conversation.** Waiting for a reply used to end in a timeout on most AI clients, and the agent dropped off the thread. An agent now holds the line, and an empty wait tells it in plain words to keep waiting.
- **Agents you run yourself can show what they are doing.** An agent joining from your own terminal used to sit on "Monitoring" however hard it was working. It can now report working, sleeping or blocked, in the same colours the Jobs board uses.
- **Tools state their rules before you hit them.** Several tools taught their own rules by rejecting you. They now say up front which fields take a single value, which need updating one at a time, and when overwriting existing content needs an explicit flag.
- **Roadmap editing got easier.** Name items the way you already see them (`BE-0001`), change one field without resending the rest, and see every problem in a rejected batch at once.
- **Agent badges agree with themselves.** The same agent shows the same initials and the same colour everywhere, and a name with a bracket no longer renders as "R(".
- **Chain member cards are single-row**, and a member no longer flips to "planning" just because you clicked it.
- **Release downloads are named after the product**: `giljo-hq-<version>.tar.gz`.

### Added

- **Agents you run yourself can now show what they are doing.** An agent that joins a
  chat from your own terminal used to sit on the blue "Monitoring" dot no matter how hard
  it was working, because only agents started from the dashboard reported a status. Such
  an agent can now say so when it posts, and its dot turns white for working, purple for
  sleeping, orange for blocked, and so on — the same colours the Jobs board already uses.
  Agents started from the dashboard are unaffected: their real status still wins, so
  nothing can talk over what the platform already knows.
- **README now covers Message Hub, Roadmap, and 360 Memory.** The three sections explain how agents coordinate across sessions, how work gets prioritized and staged, and how project history carries forward automatically.

### Changed

- **Editing your roadmap no longer means looking up ids first.** Roadmap items
  can now be named the way you already see them — `BE-0001`, `IMP-0086` — as
  well as by their full id, so your agent can rank work straight from what it
  already knows.
- **A rejected roadmap save now tells you everything that is wrong, at once.**
  One over-long note used to hide every other problem in the batch until you
  fixed it and tried again; the answer now lists every row that needs a change,
  and says what the limit is.
- **Your AI assistant now sees, up front, that overwriting an already-filled-in product field needs an extra flag.** Updating your product's tech stack, architecture, quality, or testing details when they already have values used to require the assistant to guess or fail once before learning it needed to opt in explicitly; that requirement is now documented directly on the tool it was missing from.
Chain member cards in the project strip are now single-row, showing just the taxonomy tag and current status at a glance instead of a two-row pill with a truncated project name.
After posting to a Message Hub thread, agents now get a one-line reminder in the reply itself: expect a response, and stay available to catch it. Posts that close or resolve a thread do not carry the reminder. This keeps agents attached to conversations instead of posting and walking away.
Release downloads are now named after the product: `giljo-hq-<version>.tar.gz` instead of the old `giljoai-mcp-` name. The installer reads the download location from the release manifest, so upgrading and installing are unaffected.

### Fixed

- **Your AI assistant now sees the context-tuning rules before it hits them, not after.** Reviewing and updating a product's stored tech stack or architecture used to reject with only a "too long" error, hiding the real fix (update one field at a time) behind several shrink-and-retry attempts. The assistant is now told up front which fields take a single value and which need to be updated one at a time, and a review that overwrites an existing value tells your assistant to say so explicitly instead of failing with no explanation.
- **A tuning review that changes nothing now says so clearly.** Submitting updates that could not be applied used to be reported as a success with nothing changed; it is now reported as a clear, actionable rejection instead.
- **Editing one roadmap field no longer clears the others.** Your agent can now
  move an item, or change its risk, without resending everything else about
  it — the risk, complexity and blocked note you set already stay put. Ask it
  to patch fields, and anything it leaves out is kept; anything it deliberately
  sends as empty is cleared.
- **Closed a rare project/task numbering edge case.** Hardened the internal
  numbering preview so it can never hand out a number that collides with one
  already in use, even under heavy concurrent activity.
- **Finished agents no longer pile up phantom "unread message" badges.** A
  status update or follow-up note sent to an agent that had already finished
  used to sit there forever, showing as waiting on a job that will never come
  back to read it. Those badges now stay accurate, and if a message could not
  be delivered to a finished agent you are told so.
- The Mark Superseded dialog failed to load the list of replacement projects.
- **Agent badges no longer show a stray bracket for names with a parenthetical note.** An agent name like "Reviewer (Phase 5)" used to render its badge as "R(" in some places; badges now always show clean letter initials.
- **The same agent now shows the same badge colour everywhere.** Previously an agent could appear in one colour on the Message Hub and a different colour on the Agents panel; both now agree.
- **New agent names can no longer contain punctuation** (parentheses, colons, and similar), so this class of badge glitch can't happen again. Existing agent names are unaffected.
- **A chain member no longer shows "planning" just because you clicked on it.** Viewing an unstarted project in a multi-project chain used to make its status card flip to "planning" even though nothing had actually started working on it. The status shown now always reflects what the project is really doing.
Agents can now reliably stay attached to a Message Hub thread. The wait-for-my-turn call previously held the connection exactly as long as most AI clients allow, so the default call often ended in a timeout error instead of a clean "nothing yet, call again" answer, and agents dropped off the thread. The hold is now shorter than every common client limit, and an empty wait now tells the agent in plain words to call again and keep holding the line.

### Security

- **Documentation hygiene: an error report no longer spells out its own permissive outcome.** A monitoring message emitted when a hosted-plan check errors said, in plain text, that the request proceeds anyway. The message is now a neutral error signal. No behaviour changed, and the alerting tag is unchanged.
- **Documentation hygiene: removed personal-name attribution from shipped code.** Code comments, docs, and test fixtures no longer reference an individual by name.
- **Documentation hygiene: removed internal operational detail from shipped code comments.** Internal server hostnames, timestamps, and infrastructure details that had no bearing on how the software works have been generalized or removed from source comments and documentation.

## [2.0.3] — 2026-08-19

### Highlights

- **Your AI assistant can now read a big board reliably.** It sees counts first, fetches in pages, and walks the whole list without missing or repeating a row.
- **Search for agents.** Find projects and tasks by a word — including descriptions and commit history.
- **Honest answers everywhere.** A mistyped filter tells you instead of pretending nothing matched, and an empty list explains when finished work is hiding.
- **Approvals answered right in your AI client.** No dashboard trip needed.
- **One clear "Action needed" system.** Hand-offs, mentions, and approvals share one style, click through to the exact message, and follow you between devices and reloads.
- **Agents follow the product you are working in.** Per-product agent crews, up to 16.
- **Search inside a conversation** in the Message Hub.
- **Model Context Protocol SDK 2.0** and support for the newest protocol version, plus security fixes and dependency updates.

...plus 91 more fixes and improvements, detailed below.

### Added

- **Approval requests can now be answered right in your AI client.** When an
  agent pauses to ask you to approve something, clients that support the newest
  connection standard show the choice inline and let you answer on the spot —
  the agent carries on as soon as you pick. Nothing changes for other clients:
  the request still waits on your dashboard, where it has always been, and the
  dashboard can still resolve it either way.
- **Codex worker lanes can now run headless without stalling.** When an
  orchestrator runs Codex workers without opening a terminal for each one, it can
  drive them through a new built-in helper instead of hand-writing the connection
  itself. The helper fixes the settings that decide whether a worker can finish its
  work unattended, so a lane no longer sits waiting on a confirmation prompt nobody
  can answer, and no longer reports "nothing has happened yet" for work that has
  already finished. Anything the Codex engine asks that the helper is not allowed
  to answer on your behalf is reported as a clear error instead of a silent wait.
  The engine is reached only over a local connection on your own machine, and the
  existing way of launching Codex workers in terminals is unchanged.
- **Hand-offs to you now survive a reload and follow you between devices.** When an
  agent hands work to you in a conversation, it leaves a notification on the server
  rather than only in the browser tab that happened to be open. You will still find
  it after a refresh, on a second computer, or the next morning — and it names the
  agent that is waiting. Repeated hand-offs on the same conversation leave one entry,
  not a pile.
- **See at a glance who on a conversation is still working.** A new
  `get_participant_liveness` tool reports, for every participant in a thread, when
  they were last active and whether they are active, quiet, or gone. An
  orchestrator can now tell a busy agent apart from a stalled one without digging
  through files, and an agent can check whether whoever assigned its work is still
  around before deciding to wait or escalate.
- **Agents can now wait for their turn instead of polling for it.** A new
  `await_my_turn` tool lets an agent hold a single call open until a message or
  hand-off actually arrives for it, then return immediately. Work reaches the
  right agent in under a second rather than whenever its next check happened to
  land, and waiting costs nothing while it waits. Polling still works exactly as
  before, and remains the right choice on chat surfaces that cannot keep a call
  open.
- **Your agents can now promote a task to a project on their own.** When a task
  turns out to be bigger than a task, an agent can convert it in one step and
  get exactly what the dashboard's convert wizard produces: the project is
  created from the task, subtasks and the task's roadmap card move over to it
  (keeping their place in the roadmap), and the task is removed. Previously an
  agent had to rebuild the work by hand, which left the task behind and
  quietly stranded its roadmap card. The new project arrives inactive and
  untagged, so you still choose when to launch it.
- **Your orchestrator's personality can now differ per product.** Customise the
  orchestrator prompt for one product and it applies only there; products you
  have not customised keep using your all-products prompt, and anything
  without one falls back to the packaged default. Existing customisations keep
  working exactly as before -- they simply become the all-products setting,
  with nothing to migrate. Chain runs stay consistent too: the conductor and
  the projects it drives use the same prompt.
- **Ask an assistant about your projects and you now get a focused answer
  instead of your whole board.** You can search projects by name or serial
  ("find the OAuth one"), ask for a specific number of results, and when a
  list is shortened it says so and tells you how to narrow it. The lightweight
  listing mode is now genuinely lighter than the detailed one, which it
  previously only claimed to be.
- **Search inside a conversation.** Open any conversation in the Message Hub and
  the new search box narrows it to the messages you are looking for, matching
  both what was said and who said it. Clear the box to get the full
  conversation back.
- **The orchestrator prompt editor now tells you which prompt each product is actually
  using.** While a product is selected, a line above the editor says whether that
  product is served by its own prompt, by your all-products prompt, or by the built-in
  default, and it stays correct while you browse either tab and updates the moment you
  save or remove a prompt. Saving still does exactly one thing: it writes the text on
  the tab you are looking at, and never changes or deletes the other one. Putting a
  product back on the shared prompt now has a clearly labelled action that names what
  the product will fall back to.

### Changed

- **Hand-off alerts now say who is waiting on you.** When work is handed to you in
  a conversation, the notification names the agent that is blocked — "P1
  Orchestrator is waiting on you in Laptop interop" — instead of only naming the
  conversation. You can tell at a glance whether it needs you now, without opening
  it first.
Message Hub posts now always carry an explicit author. Agents must identify themselves with `from_agent` on every `post_to_thread` call, and posting in your (the human user's) voice now requires an explicit `as_user=true` — a forgotten field can no longer make an agent's message appear as if you wrote it.
- **New agents arrive ready to configure, not switched on.** Adding an agent — or pressing
  "Add Default Agents" — used to put it straight to work in the product you had open, even
  though it was still carrying its stock instructions. New agents now appear in your agent
  list where you can open and tailor them, and go live in a product only when you switch
  them on there. Nothing runs in a product until you say so.
- **Agents you already switched on are untouched.** This applies only to agents added from
  now on; everything already enabled for a product stays exactly as you left it.
- **Agent crews now start with the right instructions once, not twice.** In
  Subagent mode each agent already loads its role from the agent file installed
  on your machine, so the server no longer sends that same role a second time.
  That leaves noticeably more room in every agent's context for the actual work.
  Multi-Terminal agents are unaffected: their terminals have no installed file
  to read from, so they keep receiving their role from the server as before.
- **A missing agent install no longer halts a run.** Previously an orchestrator
  was told to stop and report the mismatch when an agent file was not installed.
  It now carries on using your coding tool's own default agent and tells you
  once: "No Giljo HQ agent templates installed — using default agents. Run
  giljo_setup to install tuned agents."
- **Every project now lives under a product.** Creating a project without
  naming one is refused up front with a message that says what to pass, instead
  of failing deep in the database. Older installs that still held product-less
  projects get them filed under a product on upgrade — those projects are kept,
  never discarded.
- **Closeout and memory-entry tools now tell you how to avoid a save failure, not just how you'll hear about it afterward.** The `summary` field's description now says to send it as the last argument in your call, so a long note can't accidentally swallow the fields that follow it.
- **Your AI assistant now sees how big your task list is before it reads it.** Every
  task listing comes back with the totals for your whole board — how many are done, how
  many are still open, and the date range they span — so the assistant can ask a
  sensible question instead of pulling everything and hoping. Listings are also bounded
  now: you get a sensible page by default, and when there is more, the answer says so
  plainly instead of looking complete. Asking for everything still works — it is just a
  deliberate request now rather than the accidental default.

Added
- **Search your tasks by a word.** Ask for "the OAuth one" and the assistant can find it
  by a word in the title, the description, or the TSK number, instead of reading the
  whole list to look for it.
- **A lighter task listing.** A new compact view returns just what is needed to find and
  sort work — typically 35-40% smaller, depending on how long your task titles are —
  leaving your assistant more room to actually do the work you asked for.
- **Updated the dashboard's state management library to its latest major
  release.** The dashboard now runs on Pinia 4, keeping it current with the
  wider Vue ecosystem and on a supported upgrade path. Nothing changes in how
  the dashboard looks or behaves.
The per-project auto check-in slider is retired. How often waiting agents check in is now one account-level setting (Tools → Notifications, next to the silence threshold), agents on a harness with live wake support respond to new work instantly instead of sleeping on a timer, and the dashboard now tells you whether an agent is waiting for a wake signal, sleeping on a countdown, or has gone quiet. Cadence values you had set on individual projects are still honoured.
- **A cleaner Message Hub.** The toolbar above your conversations now uses the
  same compact icon buttons as the Projects page, with the number of deleted
  threads shown as a small dot on the trash icon. The conversation cards line up
  with the toolbar instead of sitting narrower than it, and the "What the
  indicators mean" panel is gone: hover any agent to read what its status dot
  means, in plain words.
- **You get told when an agent is waiting on you, wherever you are.** When an
  agent hands a conversation back to you, a notice now appears in the bar at the
  top of every page, not only inside the Message Hub. Click it to go straight to
  the conversation; if several are waiting, one notice takes you to the list.
- **The in-app Privacy Policy and Terms of Service now describe the service as
  it actually runs.** Both documents now name every third-party
  subprocessor that helps operate the hosted service, state where your data and backups are stored, and spell out
  the full retention picture: read-only access after a subscription lapses,
  permanent deletion one year later with an email reminder first, your choice
  of immediate deletion or a 30-day grace period, and how long residual copies
  can persist in recovery backups. The governing law is now stated plainly as
  New Hampshire, USA.
- **The Agents list now tells you which agents you have tuned and which are brand new.**
  The Updated column used to show the same date for every agent, because an agent that had
  never been edited fell back to the day it was created. It now reads "Never edited" for a
  stock agent, "Added today" for one you have just added and not switched on yet, and the
  real date once you have changed something — with the exact time on hover. Newest first,
  so agents that need your attention sit at the top.
- **The "Available in all products" switch in the edit screen is easier to read.** It is
  one line now, and its label stays put instead of rewriting itself as you flip it.
- **Every agent briefing now says where its orchestrator instructions came from.** Each
  briefing carries one line naming whether it is running on a custom prompt you saved for
  this product, a custom prompt you saved for your whole account, or the built-in default,
  with the date you saved it. A saved prompt used to replace the built-in one invisibly and
  stay in place through every restart, so an agent behaving unexpectedly took real digging
  to explain. Now it takes one glance, whether you are reading the agent's briefing or its
  transcript afterwards.
- **Settings now tells you when an account-wide prompt is quietly governing a
  product.** If you have saved a custom orchestrator prompt for all products,
  the System Prompt tab now says so while you are looking at an individual
  product, shows the date you saved it, and gives you a one-click way to go
  manage it. Viewing the all-products prompt itself now shows its saved date
  and makes Restore Default easy to find.
- **Saving an unchanged copy of the built-in prompt now asks first.** Saving
  text that is identical to the packaged default used to look like it did
  nothing; in fact it froze your account on that day's wording and stopped it
  receiving later improvements. Settings now warns you and waits for you to
  confirm.
- **One clear "Action needed" style for everything that needs you.** A handover, a
  mention, and a request for your approval now look and behave the same wherever they
  reach you — the banner, the bell, and desktop notifications — with a small label
  saying which of the three it is.
- **Clicking any of them takes you to the exact message,** not just to the thread, and
  the message is marked with wording that matches the reason you were called.
- **Mentions and approval requests now stay in your notification bell** until you deal
  with them, instead of disappearing with the pop-up.
- **Notifications name things, never internal ids.** Where a notification used to show a
  long identifier, it now shows the thread's name — or its short reference — instead.
- **Clearing "waiting on you" is now a hand button you can actually find.** The old
  "Mark handled" text link sat at the bottom of the thread next to the chat box and was
  easy to miss. It is now a yellow hand button that gently pulses while a thread is
  waiting on you, with a second copy beside the thread search box that stays on screen
  the whole time — so the same button also tells you at a glance whether anything needs
  you here. It respects your system's reduced-motion setting.

Fixed
- **The gold "Waiting on you" marker now disappears when you clear a thread.** Opening a
  thread from a notification and marking it handled cleared it everywhere except the
  marker itself, which stayed pinned above the message until you navigated away.
- **Desktop notifications show the Giljo face instead of the wordmark**, matching the
  rest of the app.
- **Giljo HQ now runs on version 2.0 of the Model Context Protocol SDK.** Your
  existing connections keep working exactly as before — every protocol version
  your tools already speak is still served, and there is nothing to reconnect or
  reconfigure.
- **Support added for the newest protocol version (2026-07-28).** Newer clients
  that speak it can now connect without being turned away, alongside the older
  versions Giljo HQ has always supported.

### Fixed

- **Wait-for-your-turn now works on hosted installs, not just self-hosted ones.**
  On a deployment that runs several server processes, an agent waiting for work could
  miss it when the message happened to arrive on a different process. Waiting agents
  are now woken wherever the message lands. Self-hosted installs were never affected.
Marking a project completed from an agent now finishes it properly. It runs the same full close-down the Archive button does — the project is set aside, given a real completion date, and any agents still sitting at "complete" are moved to "closed". Before, an agent could only do the halfway version, which looked finished on the dashboard while leaving its helper agents hanging around forever.
- **Your agents now follow the product you are working in.** Switching products used to
  have no effect on which agents were installed or which ones an orchestrator could
  start — every product got the same set, so agents you had tuned for one product turned
  up in another. Enable or disable an agent on the Agents screen and that choice is now
  remembered per product, and applies to what you install, what your orchestrator can
  start, and what it sees on its roster.
- **A product you have never customised keeps all of your agents**, exactly as before, so
  nothing disappears when you upgrade.
- **Turning an agent off stays off.** A disabled agent is no longer switched back on when
  you restart, upgrade, or switch back to that product.
- **Orchestrators can now start any of your enabled agents, up to 16.** The roster was
  capped at 8 while installs already allowed 16, so an agent could be installed and yet
  impossible to start.
Installing your agents can no longer overwrite files you wrote yourself. Every agent
Giljo HQ exports now says, inside the file, that it came from Giljo HQ and which product
it belongs to -- so an install refreshes its own files, leaves anything you hand-wrote
completely alone, and asks before replacing anything it is unsure about. It used to be an
all-or-nothing choice: overwrite everything in the folder, or skip the update entirely.

Changed
Exported agents are now named after the product they belong to, so the same agent used by
two products installs as two separate files instead of one quietly replacing the other.
Where your coding tool supports it, agents install into the project you are working in
rather than your home folder, which keeps each project's agents to itself.
- **The "last exported" indicator now tells you about the product you are in.** Installing
  your agents for one product used to mark them as freshly exported everywhere, so a
  different product could look up to date when it had never been exported at all — and the
  warning that you were about to ship outdated agents simply never appeared. Each product
  now keeps its own record, so the date and the "may be out of date" warning describe the
  product you are actually working in.
- **Nothing is lost when you upgrade.** Products carry their existing export date forward,
  and a product you have never customised keeps showing what it showed before.
- **Agents waiting for their turn no longer wake constantly for work that is not
  theirs.** A conversation left open to "anyone" — including ones already
  resolved, or ones an agent was never part of — used to count as that agent's
  turn forever, so an agent told to wait would report new work every moment and
  never actually settle. Waiting agents now stay quiet until something genuinely
  arrives for them, and a real hand-off still reaches them in under a second.
- **An agent you create works as soon as you switch it on.** A newly added agent could show
  up on the Agents screen and still be impossible to start, missing from your
  orchestrator's roster, and left out when you installed your agents — with nothing to
  indicate anything was wrong. Switch a new agent on for the product you are working in and
  it can be started and installed right away.
- **Your existing agents are untouched.** Adding an agent adds only that agent; the ones
  you had already enabled or disabled for a product keep exactly the settings you gave
  them, and an agent you turned off for a product stays off.
- **You can retire an agent everywhere again.** While you had a product open there was no
  way to switch an agent off across the board — the switch on the Agents list only covers
  the product you are working in, and the edit screen had no control for it at all. Editing
  an agent now offers **Available in all products**, which turns it off for every product
  at once.
- **The two switches now say which is which.** The list column reads "Active here" and its
  switch still affects only the product you are working in; the new "Available in all
  products" control in the edit screen is the one that covers everything. Turning an agent
  off for one product
  can never retire it everywhere, and turning it back on for one product can never
  un-retire an agent you deliberately retired.
- **Adding agents can no longer take you past your agent limit.** Creating an agent
  skipped the check that stops you exceeding the maximum number of active agents, so it
  was possible to go over — after which some agents would quietly stop being installed or
  offered to your orchestrator. Creating an agent is now refused with the same clear
  message you already get when switching one on.
- **Duplicating an agent gives the copy a predictable name.** The copy was labelled
  "(Copy)" on screen but saved under a different name entirely, which made it harder to
  find and to start. A copy is now named after its role, so the name you see is the name
  it keeps.
Connected AI clients no longer lose their connection when their sign-in token renews in the background. Renewals are now accepted at the same address the server tells clients to use, so a long-running session keeps working instead of stopping with an error until you sign in again.
- **Tasks and projects created by agents now always land on the product the agent
  intended, even while you switch products in the dashboard.** An agent can name the
  product it is filing against instead of relying on whichever product happens to be
  active, and every task and project it creates now tells it which product the item
  landed on.
- **Long messages now appear instantly in every open window.** A lengthy post
  could arrive live in the window that sent it while other open sessions saw
  nothing until they refreshed the page. Every session now receives it right
  away, and the full text is loaded in the thread you are reading.
- **Turning a task into a project now keeps it with the right product.** The new
  project is filed under the product the task belongs to, instead of whichever
  product happened to be selected at that moment — so switching products in
  another tab, or having an agent switch it for you, can no longer send a
  promoted task somewhere you did not expect. The confirmation now names the
  product it landed in, and if that product has been deleted the conversion
  stops and tells you, rather than quietly filing it elsewhere.
- **Projects with long descriptions now update live in every open window.** A
  change to a project with a lengthy description or mission appeared instantly in
  the window that made it, while other open sessions saw nothing until they
  refreshed. Every session now updates right away.
- **Agents with long missions appear on every screen the moment they start.** A
  newly started agent carrying a long mission could be missing from other open
  windows until the page was reloaded.
- **Editing an agent's mission works again.** Saving a mission change reported an
  error even though the change had been saved, and no open window updated to show
  it. Saving now succeeds cleanly and the new mission appears everywhere at once.
- **Two tasks in the same product can no longer end up with the same number.**
  The database safeguard behind task numbering had quietly stopped working, so a
  rare timing slip could leave you with two tasks sharing an ID like TSK-19. The
  safeguard is back, and if your database already contains a duplicate pair it is
  repaired automatically on the next start — nothing is deleted, the later task
  simply gets the next free number.
- **Editing a project no longer depends on which product you have selected.** If a
  different product was selected — or none at all — updating one of your own
  projects was refused until you switched back, even though the project was
  plainly yours. Those refusals are gone. Your projects stay private to you
  exactly as before; only the unnecessary step was removed.
- **Approval notifications now say which project is waiting on you.** When a closeout
  needs your approval, the bell and banner entry names the project in its heading and
  its message instead of showing only the reason — so with several projects in flight
  you can tell at a glance which one is asking. Approval notices you already received
  are unchanged.
- **The project shortcut on a notification works again.** Notifications that name a
  project now show a clickable project tag that takes you straight there. It had
  stopped appearing on notifications sent from the server.
Setting your server's public address with a trailing slash no longer produces broken links. Orchestrator prompts and setup download links now come out correct either way, instead of working on some paths and doubling up the slash on others.
- **The projects list's rows-per-page control no longer silently does nothing.**
  Choosing "All" asked for more rows than the server will return in one page, so
  the request was rejected and the table quietly stayed as it was — it looked
  like a dead button. The control now offers only page sizes that work, up to a
  new largest option of 200 rows, and an out-of-range choice can no longer reach
  the server at all.
Ask an AI assistant what work you have finished and you now get the whole answer. The project list an assistant reads is capped for safety, and that cap was keeping whichever projects were created most recently — so a project started months ago and finished last week fell outside the window and vanished from the list entirely, with nothing to say anything was missing. Finished work is now kept by when it was finished, unfinished work is never dropped, the cap sits two and a half times higher, and a list that does get cut short now says so and explains how to narrow the question.
- **Changing a task's product no longer silently fails.** Trying to move a
  task to a different product now shows a clear error instead of appearing
  to save while quietly not applying the change.
- **An agent asking for context now knows when it received a partial answer.** Requesting context now surfaces each category's own truncation signal instead of silently dropping it, and the open-task count always reflects the true total rather than the size of the page returned.
- **Searching projects for a name containing `%` or `_` no longer returns the whole board.** Those characters used to act as database wildcards, so a search like `100%` silently matched every project instead of the one you meant.
- **The project list tool's size-limit description now says what actually happens.** It previously claimed an over-limit request would be scaled down; it is refused instead, and the description now says so.
- **The task list tool now accepts `limit=0` to mean "use the default"**, matching the project list tool instead of returning an error.
- **Long list answers now arrive instead of being rejected by your assistant.** The size limit on project and task listings sat just above what an AI client will actually accept, so a large answer could be reported as complete and then never delivered. The limit is lower now, and anything beyond it comes back as a clearly-marked partial answer you can page through.
- **Paging a long list no longer skips rows.** When several items were saved at
  the same moment, walking through a list page by page could quietly leave one
  out — no error, no warning, just a missing row. Pages now advance on a stable
  order, so every item is returned exactly once.

Changed
- **A stale page marker now says so instead of silently starting over.** Asking
  for the next page using a marker that no longer points at anything used to
  hand back the first page again, which could keep a client looping forever.
  It now returns a clear message telling you to start the list again.
- **A typo'd status or priority filter now tells you instead of pretending nothing matched.** Filtering tasks by a status like `in progress` or a priority like `Medium` used to silently come back empty, even when matching tasks existed. Now you get a clear message naming the valid values.
- **Filtering by a nonsense "hidden" value no longer quietly shows everything.** It now tells you which values are accepted instead.
- **The project search box's advertised length limit now matches what it actually accepts**, and the project list's `mode` and status filters now show their valid options up front instead of only on a failed attempt.
- **A hand-crafted or corrupted page marker no longer causes an internal error.**
  A malformed continuation token used to make listing projects or tasks fail
  with an opaque server error and no way to recover. It now returns the same
  clear "start the list again" message every other bad marker already gave.
- **The "how many match" count no longer changes meaning partway through a
  list.** Walking a long list page by page used to make the reported match
  count quietly shrink each page, so the number meant something different
  depending on when you looked at it. It now always shows the true total match
  count, and a new "remaining" count shows how much is left in the current
  walk.

Changed
- **Large lists now page one page sooner, to guarantee delivery.** The size
  limit for a single page of projects or tasks was lowered slightly after
  testing found a narrow range where a page reported as complete could
  actually be rejected by the client before it ever reached you. The new,
  smaller limit closes that gap.
- **Project search now looks inside descriptions, too.** Searching for a project used to only match its name or serial number — now "the one about the blue UI" finds it even when that phrase only appears in the description or the project's short code.
- **Memory search now finds commit messages.** Asking "when did we fix the redirect bug" now searches the commit history saved with each project's history, not just its written summary.
- **Your assistant can now read the manual for every filter on the project list, not 3 of 18.** Filtering options like date ranges, hidden status, and detail level now show their full descriptions and valid values right where your assistant reads them, instead of only in a hidden note it could never see.
- **Asking for both a status and a status filter that disagree now gets a clear explanation instead of a silently wrong answer.** Previously the newer filter always won without saying so -- even when it quietly ignored a request to see everything. Now a genuine conflict is called out by name so you can fix the request; asking the same thing two ways still just works.
- **Asking for more project detail by number now works the same as asking by name.** A detailed project view no longer gets silently shrunk back down to a summary.
- **Asking for a lean or full task list no longer gets silently swapped for the default.** If you set `mode` to `index` or `full` on the task list, it's honored even if the old `summary_only` flag is also set — before, `summary_only` would quietly override it and you'd get the wrong-sized rows back (and a `memory_limit` you'd set could get ignored along with it).
- **Filtering tasks by type now works instead of guaranteed to fail.** Every task carries the same type tag, so filtering by it now returns your tasks instead of being refused as invalid; filtering by any other type is refused with a clear explanation instead of silently coming back empty.
- **An empty project list now tells you when finished projects are hiding, and how to see them.** Filtering the project list by type used to sometimes come back completely empty even when projects of that type existed -- they were simply completed, and hidden by the default view. Your assistant now sees a plain note explaining that projects exist but are hidden, with the exact option to pass to reveal them, instead of reading the empty list as "none exist."
- **The hidden-projects note now counts YOUR search, not the whole board.** When a project list was narrowed by more than one filter at once (a type plus a search word, a date range, or an alias), the "some are hidden" note could name a number that didn't match what you'd actually see -- promising rows a follow-up search couldn't find. It now counts your exact filters, so the number it gives you is always the real one, and it stays quiet rather than guess when nothing is actually hidden.
The in-app Privacy Policy and Terms of Service pages now show edition-appropriate content: the hosted edition lists its service providers by name, while self-hosted installs see provider-neutral wording.
The status banner at the top of the page no longer pushes the whole page down after it loads — the space it needs is held from the first moment, so the content under your cursor stays put.
- **Connecting from OpenCode now works with the copy-paste command.** The connect
  screen was handing OpenCode a command written in another tool's syntax, so the
  very first attempt failed and OpenCode answered with its help text instead of
  connecting. The command it gives you now matches what OpenCode expects.
- **Every connect command now says which tool it is for**, so a command copied
  from one screen cannot quietly end up pasted into a different tool.
- **Clearer help when a self-hosted server uses a private certificate.** The
  connect screen now explains that command-line tools built on Node, including
  OpenCode, refuse an untrusted certificate until you add it to your trust store,
  and points at the one-time walkthrough that sets that up.
- **Duplicating an agent no longer changes the original.** Making a copy of an
  agent used to quietly take over the original's "default for this role" badge
  and move the original to the top of the recently-changed list. The copy is
  now created as an ordinary agent and the original is left exactly as it was —
  including which agents get packaged when you export.
- **The waiting banner on the roadmap no longer lingers after your agent has
  already delivered the roadmap.** If you left the page or reloaded while your
  agent was still working, returning could show the "waiting for your agent"
  spinner on top of the finished roadmap until it timed out. The page now checks
  when the roadmap was last saved and clears the banner as soon as the work has
  landed, including after a dropped connection.
- **Clicking a "waiting on you" message notification now takes you to the message.**
  Both notifications land you inside the thread with the post that is waiting on you
  marked and scrolled into view, instead of leaving you at the Message Hub to find it
  yourself. This works from the notification at the top of any page and from the notice
  above the thread list, and it now also works when you click the notification while you
  are already in the Message Hub.
- Switching your active product now updates every open tab and device immediately, so you never act on a stale screen. If a browser was asleep or lost its connection and missed the change, it corrects itself the moment you return to that tab.
Clicking a "waiting on you" notification now takes you to the exact message that handed the work over, not just to the thread it lives in — so a busy conversation no longer leaves you scanning for the post you were sent to read. Every notification for the same hand-off — the banner, the bell, the strip above your threads, and the desktop pop-up — now lands in the same place, and the ones that arrive without a specific message still open the thread on its newest post exactly as before.
- **The account status badge on your profile avatar now appears.** If your
  account is on a trial, ending soon, or scheduled for deletion, the small
  badge on your avatar in the sidebar shows it again — it had stopped
  appearing, so the only warning was inside the menu itself.
- Saving a task that fails now tells you why. If the server catches something specific — like a name that conflicts with a reserved tag — you see that exact reason instead of a generic "please try again" that just repeats the same failure.
- **Task and project actions now leave a record when they fail.** Completing a task, changing an execution mode, or deleting/cancelling/restoring a project used to show a generic error that vanished as soon as you looked away — now the specific reason lands in your notifications, so you can check what actually went wrong even after the message disappears.
- **The Privacy Policy and Terms pages now open without signing in.** Following a
  direct link to either page, or opening one in a fresh tab, used to bounce you
  to the welcome screen instead of showing the document. Both pages are public
  and now open for anyone, whether or not you have an account.
- **Connecting Claude to your server works again.** Approving the connection
  on the consent screen could fail with "Invalid authorization request
  parameters" and never finish, for any app that does not name a specific
  target when it asks for access. Approving now completes as it should.
- **Pages no longer get stuck failing to load after an update.** If part of the
  app was requested during the short window while a new version was going live,
  your browser or CDN could remember that piece as missing for up to a year —
  leaving a page blank until someone cleared the cache by hand. Those responses
  are no longer stored, so the page loads normally as soon as the update
  finishes.
When a closeout or memory entry is rejected because one argument was swallowed into another, the error now tells you the fix that actually works: send the long summary as the last argument, so nothing follows it and nothing can be swallowed. It previously advised shortening the summary, which never resolved the problem and cost several rounds of failed retries — and it said so while also correctly stating that no size limit had been reached.
An agent that has gone quiet now reads the same on every screen, and it never reads as healthy when we have simply lost track of it. Opening a thread used to show a silent agent as "Monitoring" — as if it were working away — while the thread list correctly showed it as "Silent". Both now report the agent's real status, so you can tell a working agent from a stalled one before deciding whether to wait or step in.
Editing a task now saves. Reopening a task and changing its title or description previously failed with a generic "Failed to save task" message and the edit was lost — the dashboard was sending the task's own type back unchanged, and the server refused it. Your edits go through.
- Your orchestrator now lands on its project's message thread automatically, so a
  message sent directly to it actually reaches it. Previously the orchestrator told
  every agent it assigned to join the thread but never appeared there itself, which
  meant instructions aimed at the orchestrator went nowhere. Its instructions now also
  name the thread outright instead of leaving you to work out which one it meant.

### Security

- **Chats can no longer be filed against another workspace's product or project.**
  When a chat was created with a product or project named explicitly, that name was
  stored without checking it belonged to you. Naming one from another workspace is
  now refused outright. Chats you create normally are unaffected.
- **"That project isn't in this product" now tells you which product it is in, and
  what to do about it.** Switching your active product used to turn ordinary edits
  and roadmap updates into a flat refusal — and roadmap updates went further and
  reported the item as missing when it existed perfectly well under another
  product. Both now name the products involved and the fix.
- **Search engines can read your robots.txt again.** The file was answering "sign
  in first" to crawlers, which is not something a crawler can do.
- **Two bundled libraries updated to close published security advisories.**
  The nanoid and dompurify libraries were raised to their patched releases in
  response to advisories published against the versions previously shipped.
  No features or behavior change.
- **Updated bundled development libraries to patched versions.** The build now
  uses newer undici, postcss, and brace-expansion releases that resolve
  published security advisories, including a denial-of-service issue.

## [2.0.2] — 2026-08-05

Giljo HQ 2.0.2 is our biggest update since launch. GiljoAI MCP is now Giljo HQ: one headquarters for every AI agent you work with. The Message Hub has been redesigned from the ground up: calm, readable conversation cards, live agent presence, a raised hand when a conversation is waiting on you, and your-turn notifications that reach you anywhere in the app. Under the hood, this release brings a substantial security hardening pass across sign-in and connected apps, more reliable Windows installation, and dozens of fixes that make day-to-day agent orchestration smoother.

### Added

- **Connect with a focused, 11-tool view of the server.** Adding `?profile=listing`
  to your MCP server URL keeps the everyday essentials (projects, tasks, memory
  search, roadmap and context) and hides the multi-agent orchestration tools, so a
  new connection is easier to read and quicker to learn. Choosing a profile this way
  can only ever show you fewer tools, never more, so it cannot be used to reach
  anything you would not otherwise have access to.
- **See at a glance which agents are waiting on you.** An agent's message badge on
  the dashboard now stands out when it's holding a message that genuinely needs
  your attention, instead of just showing a generic unread count.
- **Chats now show which tool each agent is running in** (Claude Code, Codex, Gemini
  and the rest), detected automatically when the agent connects, and when it was last
  active. Nothing to configure, and nothing an agent can misreport about itself.
- **Rename a chat, and close it yourself.** Chats could only be named when they were
  created, and only an agent could mark one resolved, so the list filled up with
  conversations stuck on "Open". You can now rename a chat and set its status at any
  time. Chats belonging to a project keep the project's name and stay with the
  project's history, so those cannot be renamed or deleted by hand.
- **The chat list now tells you what you need at a glance**: who has joined, what tool
  each agent is running in, the last thing said, and whether anything is new since you
  last looked. It also loads in a single request instead of one per chat, so a long
  list appears noticeably faster.
- **Agents can now ask you directly for a decision.** An agent that needs your
  call can address you by name instead of writing "waiting for you" into the
  room, so the request shows up as your turn on the thread rather than
  disappearing into the conversation.
- **Thread cards can now show what each agent is actually doing.** The agent's
  live status now travels with the thread list, using the same colours as the
  Jobs board.
- **Read your Hub threads from context, without new tools to learn.** The context
  fetcher now has a `threads` category, so an agent can see your recent Hub
  conversation threads in the same call it already uses for other context: no new
  tools added to the menu, and it never writes or marks anything read.
- **Agent silence timer is now adjustable on hosted plans, too.** In
  Notification Display settings, you can raise how long an agent may go
  quiet before it's flagged as silent, handy for slower AI models that
  just need more thinking time. Your setting is private to your account.
- **A legend that explains every colour in the Message Hub.** The "?" button next
  to New Thread opens a panel describing each status dot, the thread status chips,
  and everything else on a card, one line each. It stays closed until you ask
  for it.
- **A raised-hand icon marks threads waiting on you**, next to the thread number
  on gold-framed cards, the hand and the frame always agree, and both mean one
  thing only: an agent handed you the turn.
- **"Mark handled" clears a thread that's waiting on you** without posting a
  message. The thread stays open; the gold frame and hand simply go out.
- **Park a project to set it aside without cancelling.** Parked projects are
  hidden from the roadmap and stay out of your way, but nothing is lost --
  resume them anytime by reactivating.

### Changed

- **MCP tools now show clear names and safety info in connector directories.** Every GiljoAI tool exposed over MCP now carries a short, human-readable name and accurate "read-only" / "changes data" hints, so clients like Claude and ChatGPT can present them clearly and warn before a tool makes a change.
- **Default tester, implementer, and documenter agents now speak in terms of your own project.** They no longer assume a specific test framework, coverage target, or multi-tenant setup; they follow whatever your project already uses. This applies automatically on your next update, including for accounts created before this change.
- **Agent instructions now adapt to your project's toolchain and platform instead of assuming specific tools.** The step-by-step protocol every agent follows no longer hardcodes our own test runner, Python-only code navigation, protected file names, or a Claude-Code-only task-tracking tool as if they applied to every project; instructions are now derived from your own product and the coding tool you're actually using.
- **Agent guidance and product descriptions now adapt to your product's language and toolchain instead of assuming Python and GitHub.**
- **Completing a project now updates every agent tile live.** When completing a
  project wraps up any agents still running, their status on the dashboard updates
  immediately instead of waiting for a manual refresh.
- The product now shows its current name, Giljo HQ, consistently across the app,
  the installer, and the built-in agent tools. The guide your AI agents read when
  they connect had still been introducing the product under its former name.
- The Connect page now lines up: the tool directory panel and the integration cards below it share the same width.
- Connecting a tool happens in one place. The API Keys card is now purely for viewing and revoking keys, and the older "Configurator" shortcut that opened a second, duplicate setup window has been removed.
- The Generic MCP client card now shows a copyable connector URL, so you can connect a web app or IDE (claude.ai, ChatGPT, and most editors) by pasting one link, with no API key needed.
- **Refreshed the tool logos in setup and connect screens.** Codex CLI now shows OpenAI's current mark, OpenCode now shows its official logo instead of a generic console glyph, and the Generic MCP client logo is now white for better contrast, all sized to sit evenly beside the other tool logos.
- **Chain project cards now show a Planning badge while a project is being staged.**
  Previously it looked identical to a project still waiting in the queue; now you
  can tell at a glance that work is actively underway on it.
- **Cleaner completed-project banner.** The "Project Completed and Closed" badge and its review button now stack neatly on top of each other instead of crowding side by side. In a linked chain of projects, the review button no longer lingers on a project you've already reviewed and closed.
- **You're told it's your turn no matter where you are in the app.** When an agent hands
  a decision back to you, the notification now reaches you on any page (not only when
  you already have the Message Hub open) and clicking it takes you straight to that
  conversation.
- **The Message Hub is a calmer place to read.** Threads are shown as cards carrying the
  three things worth knowing: the name, who has checked in and from which tool, and the
  last thing said. You can rename a thread in place, copy its id to hand to an agent, and
  delete it, all without opening a menu.
- **Conversations read like conversations.** Message text now renders formatting, a run of
  posts from the same agent is grouped under one name, and a very long post folds to its
  first line until you ask for the rest. The thread header shows the id ready to paste
  into any tool.
- **Less noise on screen.** The message counters, the waiting/read/sent filter row and the
  "broadcast" tag that appeared on almost every message are gone; a tag now appears only
  when a message really was sent to one person.
- **Each of the four ways to create your first product now tells you what it
  expects before you pick it**: whether it needs an agent connected to
  Giljo HQ, roughly how long it runs, and who is doing the talking.
- **Both agent-driven paths now say something useful when nothing comes back.**
  Instead of waiting indefinitely, they explain that the step needs a connected
  agent and offer to let you fill the product in yourself.
- **The end of the tour has its own way out** rather than only a "skip" link.
- **The certificate trust steps are now where you need them.** If your AI coding
  tool refuses to connect to a server running HTTPS, the walkthrough for trusting
  your server's certificate is reachable straight from Tools → Connect, and from
  the connect card itself while you are copying the command. It used to be
  available only under Startup. Wherever you open it from, ticking "Don't show
  this again on this device" is now remembered.
- **Buttons now look the same everywhere.** Round icon buttons have been
  squared off to match the rest of the app, so the same control no longer
  appears as a circle on one screen and a rectangle on another. Status dots
  and pills are unchanged.
- **Thread cards no longer grow tall when several agents join.** Each agent now
  shows as a compact badge with its harness and a status dot; hover any of them
  to see the full name and what that agent is doing. Threads with more than five
  agents collapse the rest into a "+N more" chip.
- **The thread's number now leads the card title** in yellow, and the footer
  carries the full `join_thread` command so you can copy it in one click.
- **Agent names in a thread are all the same colour now.** Colour lives on the
  badge only, so six agents in one thread no longer read as six different levels
  of importance.
- **The auto check-in control has been removed from the composer.** Choosing a
  polling cadence on every message was a decision you shouldn't have to make to
  send one; the default now lives in the agent instructions.
- **The Hub legend now floats beside your threads** instead of pushing them down,
  closes with its own ✕, and is available inside a thread too.
- **Cards only turn yellow when it is actually your turn.** Unread threads no
  longer light up the whole board; yellow now means exactly one thing: an agent
  handed you the baton. A matching strip at the top of General names the thread
  waiting on you.
- **The thread id inside a thread is copyable again**: same one-click copy block
  as on the cards.
- **The Tasks toolbar matches Projects**: compact icon buttons instead of a mix
  of text and icons.
- **GiljoAI MCP is now Giljo HQ.** Reconnect your AI tools with the new giljo_hq server name from the Connect page.
- **Agent-facing text no longer cites internal tracker numbers.** Tool
  descriptions, the routing guide, and the rendered agent protocol used to
  reference ticket IDs from our own issue tracker (references nobody outside
  the project could look up). They now say what they mean without them.
- **Clearer explanation of how task serial numbers are assigned.** The
  create-task description showed a single literal example that only ever
  applied to the very first task; it now describes the actual `TSK-nnnn`
  format.

### Fixed

- **Agent tiles now update live when a project closes.** Closing a project
  used to leave finished agents' tiles showing their old status until you
  refreshed the page. They now flip to their final state immediately.
- **Messages sent to an agent that already finished no longer go unanswered.** If you
  direct an action-required message to an agent that has since closed or shut down,
  it's now automatically forwarded to the agent still driving the project, and you're
  told right away who picked it up.
- **Commit history entries in project closeouts always show a title now.** Previously a commit recorded without a message could show up blank in the dashboard's commit history and closeout summaries; the server now asks for the commit title up front instead of saving a blank one.
- **A message to an agent that had already finished could vanish without a trace.**
  If the hand-off to the active agent failed to save, the message used to disappear
  silently. Now that failure is caught, logged, and the sender is told the hand-off
  didn't go through instead of assuming it worked.
- **The onboarding tutorial's "Read more" link now opens the right guide section.** Clicking through from the first tutorial step lands you on the guide's overview section instead of scrolling nowhere.
- **Agents in the Message Hub are no longer mistaken for you.** An agent that
  identified itself with an ID rather than a name could be shown as if you had written
  the message: your colour, your side of the conversation, and an unreadable ID for a
  name. The Hub now takes each author's identity from the server instead of guessing
  from the shape of their ID, so agents always look like agents.
- **Everyone who speaks in a chat now appears in its participant list.** Previously
  only broadcasts on a project chat registered anyone, so direct messages and chats not
  tied to a project could show a conversation with nobody listed as taking part.
- **An agent's name sticks once it introduces itself.** A name supplied when joining a
  chat used to be discarded if the agent had already been added automatically, leaving
  it permanently nameless.
- **Project chats can no longer be deleted by accident.** The delete button was hidden
  for them but nothing actually stopped it, so a chat holding a project's history could
  still be removed and, if nobody noticed within 30 days, permanently erased.
- **Chats belonging to a project now show the project's name** instead of a placeholder.
- **An agent's tool is no longer forgotten.** An agent detected as Claude Code or Codex
  could be quietly relabelled as generic after posting from somewhere we could not
  detect; the Hub now keeps what it knows.
- **Multi-project chains no longer lose their coordination chat.** Each chain's
  chat is now linked directly to the run, so every agent working the chain finds
  it reliably. Previously this depended on the run's id being spelled out in the
  chat title: if the title changed, agents quietly stopped finding the chat and
  went silent with no error. Existing chains are relinked automatically, and
  chain chats now keep their history when the chain finishes.
- **A chain can no longer end up with two coordination chats.** If a chain is
  restarted or retried at the point where its chat is created, the second attempt
  is now pointed back at the chat that already exists instead of quietly opening a
  rival one, which used to leave some agents talking in one chat while the rest
  waited in the other. Where an old chain's chat cannot be identified with
  certainty, it is left as it was rather than guessed at.
- **Handing off a chat turn to someone who cannot receive it is now refused
  instead of quietly lost.** Passing the turn to a name that nobody on the chat
  answers to used to report success while the turn went nowhere; the agent
  waiting for it simply never woke up, with nothing to show why. The hand-off is
  now declined on the spot, and the message lists the names that would work.
- **Addressing someone by their display name instead of their id is caught before
  the message is sent.** Chats show a friendly name next to an id, and addressing
  the friendly name sent the message and the turn to nobody: the commonest way a
  hand-off went missing, because the turn follows whoever the message is addressed
  to. Both are now checked, and the refusal tells you the exact id to use. If two
  members have genuinely claimed the same name, it says so plainly and explains how
  to clear the clash rather than guessing which one you meant.
- **An agent messaged directly on a chat can read and clear that message without
  joining first.** Being sent a message that needs a reply used to count against
  the agent while leaving it unable to mark the message as read, which could hold
  up finishing its work. Anyone you message directly is now added to the chat's
  member list as part of sending, and existing chats repair themselves the next
  time the agent reads them.
- **An agent that stops responding after finishing its work can now be accepted,
  not written off.** If an agent goes quiet before reporting in (but you can see
  its work is done), you can record what it delivered and close it out normally.
  It shows as closed on your dashboard instead of being filed alongside agents
  that failed or were abandoned. When closing such an agent is refused, the
  message now spells out how to accept it instead of leaving you to guess.
- **Blocked completions now name the step that unblocks them.** If an agent
  cannot be completed because it left unfinished items or unread messages
  behind, the message names the call that settles them, and no longer assumes
  the person reading it is the agent whose list it is.
- When an agent stops responding and you look into its job, the dashboard no longer treats your own check as a sign the agent woke up. Previously, opening a stalled agent's task list quietly marked it active again, which hid the guidance telling you how to accept its finished work. Only the agent's own activity clears the "not responding" flag now.
- Two housekeeping jobs that quietly stopped working now run again. Old resolved
  notifications are cleared on schedule instead of building up forever, and items
  you deleted more than 30 days ago (threads, tasks, vision documents and agent
  templates) are permanently removed as intended. Both had been failing silently
  in the background since an internal safety check was tightened, so nothing was
  ever lost or exposed; the cleanup simply never happened. Self-hosted installs
  are the ones affected, since there is no operator to tidy those tables by hand.
- **Every field on the product card can now be filled in.** Notes about your
  developer tooling had nowhere to go before and ended up crammed into the
  architecture notes; they now have their own place under the tech stack.
- **Running the analysis a second time no longer wipes the fields you had not
  filled in yet.** Previously, once a section had any content at all, a follow-up
  or repair run threw away everything else in that section, including boxes that
  were still empty. Now only the boxes that already have something in them are
  protected, and the rest fill in normally.
- **Summaries that do not match a document are reported instead of vanishing.**
  If your assistant sends a summary for a document that is not there, you are told
  which one and why, rather than being shown a success message for work that was
  quietly dropped.
- **Analysing a large set of documents no longer fails partway through.** The
  instructions used to demand one enormous submission, which could exceed what the
  connection would carry and lose the whole run. The work is now sent in stages,
  and your assistant is told exactly what is still outstanding instead of having to
  guess whether it finished.
- **A clearer message instead of an unexplained error** when a project folder path
  is too long.
- **Your context depth settings no longer reset themselves.** Saving anything on
  the Settings → Context tab used to quietly restore two of the six depth options
  to their defaults, so a narrower tech-stack setting came back full-size the next
  time you saved. Options you don't change are now left alone.
- **Agents get a clear error instead of silently wrong-sized context.** Passing an
  unrecognised context-depth option now returns an error naming the option and
  listing the valid ones, rather than quietly falling back to the default amount.
- **The tech stack detail setting now actually changes how much your agents
  see.** The context-depth setting for tech stack sections was previously
  saved but had no effect. Choosing "required" now genuinely trims what's
  included, instead of always sending everything.
- **Deleting an agent now actually removes it.** A deleted agent no longer
  reappears in your exported agent files or gets used when starting a new
  agent; before this fix it could still be spawned, and could still be
  written back into the ZIP files you download or sync to your CLI.
- **Starting a project from a starter template on the welcome screen no longer fails.** New users who picked one of the suggested starter projects saw an error even though the project had already been created, and clicking again created another copy. The project is now created once and opens normally.
- **Creating a project without choosing a project type no longer returns an error after creating it.** This affected the welcome-screen templates as well as anything creating a project through the API, such as your own tools and scripts, which now get the new project's full details back straight away.
- **Looking up your active project now reports its project type** instead of leaving it blank.
- **Setup now works when you connect from ChatGPT.** Running setup from a hosted
  chat connector used to return instructions for installing files into folders
  that session has no way to write to: no error, just steps that quietly could
  not be followed. Those sessions now get their agent templates returned directly
  in the response instead, in plain Markdown with no editor-specific formatting.
  Desktop apps and terminal tools keep the normal file install unchanged.
- **Your server log no longer fills up with routine "nothing happened" entries.**
  The background task that records API usage wrote a line every five minutes even
  when it had recorded nothing (roughly 288 entries a day on a quiet server),
  crowding out everything worth reading. It now writes that line only when it
  actually recorded something, so the log shows real events instead of chatter.
- **Starting work from the command line now shows up in the dashboard straight away.**
  Staging a project from a CLI or headless agent session used to leave the dashboard
  silent; the work really was happening, but the orchestrator card never appeared
  until you navigated away and came back. It now appears live, exactly as it does when
  you stage from the dashboard.
- **Asking for an agent that does not exist now tells you so, instead of quietly
  giving you a generic one.** Spawning against an agent name that resolves to no
  template is rejected outright, and the rejection lists the agents you do have,
  so the wrong agent never starts work in the first place.
- **Deleting an agent template no longer silently strips the identity from agents
  that are still running.** An agent whose template was deleted mid-run now
  receives an explicit note saying what happened and what to do about it (restore
  the agent from the trash, or re-run the work against one that exists) instead of
  carrying on with no role, no rules and nothing to explain the drop in quality.
- **Linked projects now run in the execution mode you picked for the chain.**
  If you set up projects one at a time and then linked them together, going
  straight to Implement Chain left each project running in the mode it was
  set up with individually: quietly ignoring the mode you chose for the
  chain, and in some cases handing a single project two conflicting sets of
  instructions at once. The chain's mode now decides for every project in it,
  including when you press Play on one member on its own. Once a project in
  the chain has been launched the mode is locked so it cannot change under
  agents that are already running, and if a project has no mode of its own the
  message now tells you which one to fix.
The API reference for the chain conductor prompt endpoints now describes what they actually return. It previously promised the conductor's entire protocol inline, and attributed the returned job to the first project in the chain. In reality you get a short bootstrap prompt addressed to the chain's own dedicated conductor, which then fetches its full protocol itself. Anyone reading the API docs (or writing tests against them) was being told the wrong thing.
A deleted agent no longer appears in the list of agents you can start. Deleting an agent removed it from your agent list but not from the list the system accepted when starting one, so a deleted agent could still be chosen and would then start with no instructions. Starting a deleted agent is now refused, and the message tells you which agents are actually available.
- **A deleted product's 360 memories and git commits no longer appear on the
  Dashboard.** They kept showing in the Memories and Commits panels, and kept
  inflating the Commits counter, until the product was permanently purged.
- **Purging a deleted project now also clears its 360 memories from the
  Dashboard.** Whether you purge it yourself or it expires out of the trash on
  its own, its entries are still kept for history but no longer show in the
  Memories panel or count toward the Commits total.
- **No more confusing cookie warning when you set up your account.** Creating
  your administrator account on a standard local install used to log a warning
  telling you to go configure a network setting you do not need. Local
  addresses are now recognised as the normal setup, so the log stays quiet.
  Installs reached over a custom domain still get the notice, worded plainly:
  it explains that the sign-in cookie is limited to that one address, and that
  the setting only matters if you sign in across several domains.
- **Copying an agent's launch prompt no longer fails when that agent has no
  mission written yet.** The Play button returned an error instead of a
  prompt; it now copies normally and simply shows an empty mission preview.
- **Agent details now report the right timestamps.** Looking up a single agent
  could fail outright, and finished agents were shown as if they had never
  completed. Agent details are now read from the same source as the agent
  list, so both always agree.
- **A project closeout can no longer be recorded with garbled text and missing details.**
  When the assistant's own tool-call formatting merged one field into the end of another,
  the closeout summary could be saved with raw markup on the end while its tags or commit
  list vanished silently, with no error shown. Those calls are now refused with a message
  naming exactly which field was swallowed and what to shorten, and nothing is written until
  it comes through cleanly. Summaries that simply quote that kind of markup are unaffected.
First-login workspace setup no longer fails when your chosen workspace name is already taken: a unique address is generated automatically. Agent messaging no longer errors when an agent joins a conversation with a long role description, and project git history displays correctly even when a commit has no recorded date.
The message hub list no longer errors once you are part of more than one conversation.
- **Agent-silent bell notifications can now be dismissed for good.** Notifications about an agent going silent no longer come back after a page refresh, and clicking the X on one now actually removes it instead of quietly failing.
- **Task status changes now update the dashboard task list live.** Changing a
  task's status, or creating a new task, used to require a manual page
  refresh before it showed up correctly. It now updates automatically.
- **The Connect page now remembers which tools you've configured.** Setting up
  a coding tool used to show "Waiting to connect" again every time you left
  and came back to the Connect page, even though it was already working. It
  now reliably shows "Configured," and flags a tool that needs you to sign in
  again.
- **Nothing is copied to your clipboard unless you ask for it.** Attaching a
  vision document during setup used to quietly take over your clipboard. The
  prompt is now shown on screen with its own **Copy discovery prompt** button,
  so copying is always something you chose to do.
- **A copy button no longer claims success when the copy failed.** In the
  certificate step, the green check appeared whether or not the command
  actually reached your clipboard, so the step looked finished when you had
  nothing to paste.
- **Setting up your first product no longer gets stuck on "Waiting for your
  agent's analysis".** If the app could not load your product at the moment
  your agent finished, it gave up silently and never moved on. It now keeps
  checking and continues once the product is available.
- **"Next: activate your product" now actually appears.** The reminder shown
  after you choose to fill the product form in yourself was being missed for
  the rest of the session.
- **Your first product can no longer end up without a name.** If your agent
  never named it, you are asked for one before the product is activated.
- **Hover icons no longer sit on top of the thread title.** The copy and delete
  buttons now have their own space instead of overlapping the text.
- **The "To" list in the message composer shows real agents again.** Every option
  was rendering as a blank "??" chip, so there was no way to tell who you were
  about to message. Options now show each agent's name, badge, harness and current
  status, with the Giljo mascot marking "Everyone here".
- **Refreshing rapidly no longer throws you into the first-time setup screen.**
  If the server briefly rate-limits or hiccups, the app now keeps you on the
  page you were on instead of mistaking the busy server for a brand-new,
  unconfigured install and sending you to the account-creation wizard.
- **A busy server no longer signs you out.** Being temporarily rate-limited is
  treated as "try again in a moment" rather than as an expired session, so your
  session survives a burst of activity.
- **The Git/Serena setup reminder no longer flashes on screen.** The reminder
  now waits until it knows whether those integrations are actually turned on,
  so it stops appearing for a split second on machines that already have them
  set up, and it stays quiet if that check can't be completed.
- Setup download links no longer hand back an out-of-date copy of your agent templates. If you generated a second link and edited a template in between, the older link could still serve the pre-edit version; it is now refused with a clear "re-run giljo_setup for a fresh link" message so you always get current content.
- **Deleting one agent no longer hides all your other agents.** If an agent was
  assigned to a product and you later deleted or deactivated it, your agents
  could stop appearing entirely when an assistant asked for the team roster,
  even though the rest were still there. The roster now lists every agent that
  is genuinely available.
- **A deleted product's name no longer appears beside your recent projects on the
  dashboard.** After you deleted a product, its name kept showing next to its
  completed projects until the trash was emptied. The projects themselves stay on
  the dashboard exactly as before; only the deleted product's name is gone.
- **Deleted projects no longer count as if they still existed.** Project totals
  and per-tag project counts returned by the API now cover only the projects you
  still have, instead of including everything you had ever deleted.
- **A tag can now be removed once the projects using it are all in the trash.**
  Removing it previously failed while a deleted project still referenced it. Those
  projects stay in the trash and remain recoverable; they simply come back without
  a tag.
- **The "move product to trash" dialog now shows real numbers and an accurate
  warning.** It previously listed blank counts and said your projects, tasks and
  vision documents would be deleted along with the product. They are not; they
  stay exactly as they are while the product sits in the trash, and are removed
  only when the product itself is permanently deleted, whether you do that
  yourself from the trash or it happens automatically after 10 days. The dialog
  now shows how many projects, tasks and vision documents are kept, and says
  plainly what happens to them.
- **The delete dialog no longer shows the previous product's numbers.** If the
  impact figures could not be loaded for the product you were deleting, the
  dialog could still be showing the counts from the last one you looked at.
- **Agents no longer miss a task assigned to them in a busy chat.** When a
  coordinator hands out action items to several agents on the same thread, each
  agent now reliably sees its own outstanding request when it checks for work,
  even after the coordinator moves on to direct someone else. Previously a new
  assignment to one agent could hide another agent's still-open request.
- **Unread message counts no longer get stuck on agents that have finished
  their work.** Previously, closing out a finished agent could leave a
  "phantom" unread badge behind forever. Now, informational messages are
  cleared automatically, and any message that genuinely needed action is
  handed off to the orchestrator so it's never silently lost. The dashboard
  also now shows, per agent, which messages actually require action versus
  which are just informational.
- **The Completed date on your projects is now the real completion date.** The
  column used to fall back to "last modified" whenever a completion date was
  missing, so archiving or editing a finished project quietly changed the date it
  showed. Projects are now dated the moment they finish, whichever way you close
  them (from the dashboard or through your agents), and existing projects have
  been given a completion date based on their closeout record.
- **Filtering projects by completion date works again.** Asking for everything
  completed in a date range returned nothing, because most finished projects had
  no completion date stored at all, and even once they had one, the search still
  quietly left out the projects you had already finished. Searching by completion
  date now includes finished projects automatically, so the results are the ones
  you asked for. Sorting by the Completed column is fixed too.
- **Rotated log files now show up in the log menu and can be downloaded.** The
  archive list only recognised an older log-naming style, so the rotated history
  the server actually writes never appeared and could not be fetched; only the
  live log could. Archives are now listed newest first, labelled with their date
  and rotation number, and older archives from previous versions still appear.
- **Project closeout no longer claims a standalone project was closed when it wasn't.** Closing out a project used to always say "Project closed," even for a standalone project, where closeout intentionally leaves the project open until you archive it. The message now says plainly when a project still needs to be archived to finish it, and points at the Archive action that does it.
Custom extraction instructions you type for a product no longer vanish from the form: the server now returns them, so the field shows your saved text instead of clearing itself after an analysis completes.
- **The "Time for a context review" banner now opens the right screen.** Its "Review context" button takes you straight to that product's context-tuning dialog instead of the generic Tools page.
- **Notices about a skipped Implement step now name the project and link to it.** When a project is closed out without pressing Implement, the alert now shows the project's name and tag, links directly to it, and explains calmly that the work was saved: it just ran headless or was closed from the command line.
- **Context reviews no longer suggest deleting things you plan to build.** The tune-context review now treats your product context as both what's built and what's intended: it looks for new work to fold in, keeps planned-but-unbuilt items instead of proposing their removal, and labels each finding as added, contradicted, or intended.
- The notice telling you a project was closed out without an Implement click now reliably stays in your notification bell, where you can click straight through to the project. It was previously addressed to the status banner, which never displayed it.
- Long notification titles now wrap and are fully readable instead of being cut off mid-sentence. Titles are slightly smaller and bold so they still stand out from the message beneath them.
- **Memory search always shows results for what you actually typed.** Typing, pausing, then typing more could briefly display results for the earlier text when the first search came back slower than the second.
- **The certificate dialog now keeps keyboard focus inside it and closes with Escape.** Tab could previously move focus to the page behind the open dialog, which made it possible to open a second copy on top of the first: closing one then looked like the close button had not worked.
- **MCP call counts no longer disappear for MCP-only servers.** If your server
  only ever received MCP tool calls in a given window (no regular API
  traffic), those call counts were silently dropped instead of being saved:
  the dashboard's MCP statistic would permanently under-report. They are now
  recorded correctly.
- **The Git and Serena icons on a project's Launch tab no longer flash a false "disabled" state while their status is still loading.** They now show a neutral "checking" look until the real status is known, and if the check can't reach the server they stay neutral instead of wrongly reporting your integrations as turned off.
- **A message the server turns down no longer looks like it was sent.** If the Hub
  declines a message (for example when the agent you picked shares a name with another
  one, so it cannot tell which you meant), the composer now keeps what you typed and
  tells you why, instead of clearing the box and reporting success.
- **Vision documents you move to the trash are no longer readable through the
  API.** Four read endpoints still returned a trashed document (its chunk text,
  its AI summary, its listing and its token totals) even though deleting it
  reported success and the main document endpoint already treated it as gone.
  Trashing a document now removes it from all of them consistently, and
  restoring it brings everything back together. These are API endpoints with no
  screen of their own, so there is nothing new to see in the app.
- **The full test suite now passes on a self-hosted install.** A few tests
  checked for developer-only reference documents that aren't shipped with the
  product, and failed when those documents were absent. They now skip cleanly
  when the documents aren't present, so `pytest` runs green out of the box on a
  self-hosted setup.
- **Running the test suite on a fresh install no longer stops before it starts.** The
  download included a folder of tests for developer tooling that isn't shipped with it,
  and one of those tests halted the entire run with an import error. Those tests have
  been removed from the download; every test that checks the software you actually
  received is still there.
- **The Windows installer no longer reports success when Python or Node.js
  failed to install.** A fresh Windows ships placeholder "app execution alias"
  entries for Python that look like a real install but only open the Microsoft
  Store. The installer already knew to work around them when checking what you
  had, but its final confirmation step could still be fooled by one, so a
  failed download was reported as installed and the setup broke later, well
  away from the real cause. It now verifies it can actually run what it just
  installed.
- **The Start Giljo HQ shortcut in `scripts/` now launches the server.** It was
  starting the wrong component from the wrong folder, so it could not find its
  own Python environment. It now runs the same startup used everywhere else,
  and keeps the window open to show the error if something goes wrong instead
  of closing instantly.
- **Automated, unattended installs no longer hang forever when an existing
  installation is found.** The installer asked which to do (update, reinstall,
  or cancel) with nobody there to answer. It now stops immediately and explains
  how to say what you want, rather than waiting indefinitely or guessing and
  overwriting an installation you meant to keep.
- **Installing now works when something else is already using port 5432.** If
  the database ends up on a different port (because you already run PostgreSQL,
  a second Linux environment, or a Docker container using that port), the
  installer now finds the port it actually landed on and uses it everywhere,
  instead of assuming 5432 and failing.
- **A database that cannot be reached now says why.** Setup used to print only
  "run this script by hand", with no mention of the underlying error, which an
  automated install could not act on. The real connection error is now shown,
  and it names the host and port that were tried.
- **On Windows, a busy port 5432 is reported before anything is installed,** in
  plain words, rather than after a several-minute silent PostgreSQL install fails.
- **Asking for a log file with an unusually long name no longer returns a server
  error.** On Linux installs it failed with an internal error instead of a plain
  "not found"; both the log list and the download now answer cleanly.
- **Typing in Japanese, Chinese or Korean no longer sends a half-written
  message.** In the Message Hub, pressing Enter to confirm a word suggested by
  an input method now confirms the word, as it should; it no longer posts the
  unfinished message. Enter still sends a finished one.
- When a project closeout is rejected because one of its fields never arrived,
  the error now explains what actually happened. Long entries can get folded
  into the summary field on their way to the server, so the field that follows
  goes missing: previously the message simply said that field was required,
  sending you to rewrite something you had already filled in correctly. It now
  names the field that swallowed the other one, gives its length, and tells you
  to shorten it. Nothing is saved when a closeout is rejected this way.
- **Agent terminals now launch on self-hosted Windows machines without PowerShell 7.**
  When your self-hosted server spawns agent terminals on a Windows machine
  that only has the built-in Windows PowerShell, the launch commands now use
  it automatically instead of assuming PowerShell 7 is installed.
- **Update notices now appear on servers cloned from a repository whose default
  branch is not named "master".** The built-in update check now detects your
  git remote's default branch (for example "main") instead of assuming
  "master", so "updates available" notices work on every clone. If detection
  fails, the previous behavior is kept.
- **The product update API no longer silently ignores product-memory changes.**
  Previously it accepted a product_memory value, discarded it without saving,
  and still notified open dashboards as if the memory had changed. It now
  clearly rejects the field with guidance to use the product memory tools, and
  no false change notification is broadcast.
- **Project closeouts no longer get stuck on already-read messages.** The
  completion check now looks at the same read receipts your agents create
  when they read their threads, so a fully caught-up team can close its
  project, while a genuinely unanswered action request still blocks the
  closeout until it is read. The closeout summary also reports the true
  message status instead of always claiming everything was read.
Text across the app now follows a consistent size hierarchy, so titles, body text, and captions read as distinct tiers instead of all rendering at the same size.

### Security

Updated the encryption library that protects sign-in tokens to a version that fixes a published security advisory, along with routine updates to several supporting libraries.
- **Hardened the app-authorization step.** When you connect an app or
  integration, the one-time authorization code can now only ever be used once, so it
  can never be exchanged for more than one set of access tokens, even if two
  requests arrive at the same instant. If an authorization code is ever presented
  a second time, any tokens already issued from it are revoked immediately.
- **Revoking a connection now takes effect immediately.** When a connection's
  refresh token is revoked (or a reused one is detected), the access tokens
  already issued from it are now invalidated at once: a revoked session can no
  longer keep making requests until the old token would have expired on its own.
- **The tenant-isolation guard now blocks a bulk update or delete it cannot scope to your
  account, instead of only logging it.** This closes a narrow gap where an unscoped write with
  no way to determine which account it belongs to would previously go through; correctly
  scoped writes are unaffected.
- **Two more account-data areas are now covered by the automatic tenant-isolation
  safeguard.** Hub conversation threads and their participant lists get the same
  defense-in-depth protection already applied to other account data, closing a
  gap where they were invisible to that safeguard.
- **A rare cross-account write pattern is now blocked instead of silently
  allowed.** A database write that carried an account check, but where that
  check named the wrong account, is now rejected instead of proceeding.
- **Closed the last known gaps in tenant data isolation.** Notifications, roadmaps,
  roadmap items, and chain runs are now covered by the same automatic account-isolation
  safeguard already protecting your other data (no user-visible behavior change).
- **Updated a bundled YAML parsing library to a newer version that is not affected by a known denial-of-service issue.**
- **Expanded the pre-release leak scan to cover more of the published code.** The
  automated scan that keeps private addresses, internal machine names and developer
  folder paths out of the published code now covers more of the packaged files, and
  the list of covered files is read straight from the packaging step, so a newly
  published script cannot quietly fall outside it.
- **Log downloads now serve only files that really live in your log folder.** If
  an entry in that folder is a symbolic link pointing somewhere else on disk, it
  is no longer listed or offered for download.
- **An account-isolation safeguard that trips while reading context now stops the request
  instead of being passed off as a routine hiccup.** Reading a product's agent list treated
  any failure while matching agents to the product as harmless and carried on showing the
  full list, and the surrounding context read turned such failures into an ordinary "this
  section did not load" note. An account-isolation safeguard is neither harmless nor
  ordinary, so it now halts the request and returns the standard not-found response, with
  no internal diagnostic text reaching the caller. Genuine momentary failures are unchanged:
  still reported against the section that failed, while every other section loads as before.
- **More reliable sign-in continuity and stricter token replay handling.** When
  a connected tool refreshes its session from two places at the same instant -
  something busy connectors legitimately do - both requests now succeed with
  the same renewed credentials instead of one of them locking the whole session
  out. Genuine token replays are still detected and shut down the affected
  session family immediately. Renewed credentials are also only handed out
  after they are durably saved, so an interrupted request can no longer leave a
  tool holding tokens the server does not recognize.
- The hosted service now caps how many OAuth client registrations it will accept in total (operator-tunable, default 5000). Before this, anyone could anonymously register unlimited clients until the server's client cache silently stopped loading - which would have broken sign-in for every connector. At capacity, new registrations get a clear "temporarily unavailable, retry later" response and the operator is alerted; already-connected tools are never touched.
- **The hosted edition now refuses to start without its configured public
  address.** Previously, if that setting was missing, sign-in and connection
  URLs could silently be built from request headers - which a malicious party
  could influence. The server now stops at startup with a clear message until
  the address is set, so those URLs always come from trusted configuration.
  Self-hosted installs are unaffected and keep their flexible reverse-proxy
  behavior.
- **Stricter checking of OAuth request values.** The sign-in and token
  endpoints now reject a wider range of hidden control and line-break
  characters in request fields, and a resource address must be a well-formed
  web URL with no embedded username or password. This closes edge cases where
  malformed input could distort server logs or slip past address checks.
- **Sign-in rate limits can no longer be sidestepped.** The protection that
  throttles repeated login, registration, and connection attempts now applies
  to every request and can't be turned off by a crafted request header.
- **Stronger protection for connecting third-party apps.** Connecting an app with
  OAuth now always confirms the one-time proof tied to that sign-in, closing a
  gap where a stolen authorization code could otherwise be redeemed.
- **App-connection token requests are now rate limited.** The endpoints that
  exchange, refresh, and revoke app-connection tokens now cap how many
  requests a single address can make per minute, shutting down brute-force
  guessing of connection secrets and the server load it causes. Limits are
  generous for normal clients, tunable by the operator, and self-hosted
  localhost use is unaffected.
- **Sign-in tokens are now encrypted while briefly held in the server-side
  cache.** During the short window that protects against duplicate sign-in
  requests, the server keeps a copy of the freshly issued tokens so an honest
  retry gets the same answer. That copy is now stored encrypted, so no
  readable token ever sits in the cache - on hosted deployments this closes
  the path where cache storage or monitoring could have exposed live
  credentials. If a cached copy ever becomes unreadable, the sign-in simply
  proceeds normally instead of failing.

## [2.0.1.1] — 2026-07-17

### Added

- **Your AI agent can now create your first product for you.** Two new MCP
  tools let a connected coding agent create a product and write its vision
  document directly — so during onboarding you can paste one prompt into your
  CLI and watch the product card fill itself, instead of typing everything
  into the form. Agent-written vision documents appear in the dashboard
  exactly like uploaded ones.
- **The onboarding tutorial now remembers where you left off.** Your progress
  through the tour and the starting path you picked survive a reload or a
  later revisit.
- **Review a completed project straight from its notification.** Closeout
  notifications now open the project's Implementation tab, where a new
  "Review project" button next to the "Project Completed and Closed" badge
  reopens the closeout summary — outcomes, decisions, and commits — with a
  one-click Close that safely acknowledges an already-completed project.
- **A new animated welcome tour.** After setup, GiljoAI now walks you through
  how it works in five short animated steps — your tools, your product, your
  agent crew, missions, and memory — instead of a wall of text. It ends by
  asking how you want to start (import an existing codebase, shape a new idea,
  upload a vision document, or fill the form yourself) and carries you all the
  way to your first activated product.
- **Gil now speaks through your banners.** The top-of-screen notices (updates
  available, skills out of date, and more) now lead with Gil's face, so it's
  clear when Gil is giving you a heads-up. The home-screen nudges — "activate
  your product", the Git/Serena connect tip, and the tune-your-agents tip — now
  live in this same banner instead of as separate pop-in cards: one consistent
  banner, one voice. If you'd already dismissed those tips, they stay dismissed.
- **A gentle 14-day context-review reminder.** When your active product hasn't
  had its context reviewed in two weeks and you've completed work since, a
  banner suggests tuning it so your agents keep building with an up-to-date
  picture. You can dismiss it, and it stays off if you've turned the reminder
  off in your notification settings.
- **One-click "Add Default Agents" on the agent template page.** Bring back
  the built-in agent templates at any time — the import only ever adds:
  templates you edited are kept as-is (the fresh default arrives alongside
  them as a "-duplicate" copy), and defaults you already have are skipped.

### Changed

- **Agents can now hand over the turn in the same call that asks the question.**
  Posting to a Message Hub thread accepts a `pass_baton_to` option that moves
  the thread's turn atomically with the post, and a message sent directly to
  one participant that requires action now hands them the turn automatically —
  so the recipient's "is it my turn" check can no longer miss a question that
  forgot the separate hand-off step.
- **You can now keep up to 16 agent templates active at once (was 8).** Activate up to 15 of your own agents alongside the reserved Orchestrator, and the "Your Team" badge and Agent Template Manager count both reflect the higher limit.
- **The "time for a context review" reminder now follows your reminder threshold.**
  The banner that suggests reviewing a product's context appears once you've
  completed as many projects as your reminder setting specifies, rather than on a
  fixed two-week timer. Reviewing your context resets the count, so you won't be
  reminded again right after you've just tuned it.
- **A clearer way to connect your coding tools.** The setup wizard now walks you
  through your tools one at a time, with a live status card that turns green the
  moment a tool connects — nothing to click. Pick from six tools, including
  OpenCode and any generic MCP client, and the wizard shows the exact one-command
  (or one-config) setup for each.
- **A tidier Tools connect page.** Your connected tools now live in a single
  directory with live status, and "+ Add a tool" walks you through connecting a
  new one right there.
- **The in-app User Guide caught up with the app.** Every chapter was
  reconciled against the shipped product: new chapters for the Message Hub and
  the Roadmap, an accurate walkthrough of the redesigned setup wizard and
  connect directory, chain projects, the animated welcome tour, backups and
  account security, and a new "Limits at a glance" table with the real numbers
  (7 custom agents + the orchestrator, 2–5 projects per chain, and more).
  Outdated content — the retired learning module, old Message Hub tab names,
  and stale limits — is gone, and the hosted billing chapter now describes the
  current account-deletion and backup/restore flows.
- **Release notes now ship with every change, enforced automatically.** Each improvement or fix records its own release-note line as it is built, and an automatic check keeps the set complete — so release notes are always current, with nothing left behind at release time.
- **Quieter server shutdown logs.** The step-by-step shutdown progress banner no longer floods the log output, so error details around a shutdown stay visible. The full per-step detail is still available at debug log level, and any step that fails or times out is still reported by name.

### Fixed

- **Agent setup downloads always reflect your current agents.** A setup link now
  refuses to hand back an out-of-date bundle: if your agent templates changed
  after the link was created, the download reports that it is stale so you can
  re-run setup for a fresh one — no more installing a snapshot that is missing
  templates you just added.
- **Your own agents are never crowded out by the built-in defaults.** Agent
  exports now prefer the agents you created and include up to 16 enabled agents,
  so a full set of built-in defaults can no longer push your custom agents out of
  the download.
- **Long agent names no longer break the Message Hub or chain runs.**
  Broadcasting, handing off, or directing a message on a thread that includes a
  participant with a long agent name now works reliably instead of failing, and
  chain runs accept a long conductor name for the same reason.
- **Clear message when a product or project name is too long.** Naming a product
  or project with more than 255 characters now shows a friendly validation
  message on the form (with a live character counter) instead of failing with a
  server error.
- **Reminders reliably reappear on always-on servers.** The "update available"
  and "skills out of date" banners are now re-checked periodically, so a
  dismissed reminder comes back as intended while the condition still applies —
  previously, on a server left running for a long time, it might not return.
- **The agent template page's filters now work.** The status filter offers only Active and Inactive (the states templates actually have — the old Archived and Draft options always showed an empty list), the category dropdown now filters by agent role, and the Export Status column is sortable so out-of-date templates are easy to find.
- **Closing out a project now returns you to the Projects page instantly.**
  Previously the jobs view lingered for a couple of seconds after Close, and
  the Review button could be clicked again during that window.
- **Clearer message when two actions collide.** Uploading a vision document whose
  name already exists, or importing the default agents twice at the same moment,
  now returns a clear "already exists" message instead of an unexpected server
  error. Retrying is safe.
- **The onboarding tutorial recovers if its draft product disappears mid-setup.**
  If the product the tutorial created is deleted while you are still on the upload
  step, the next document upload now starts a fresh product instead of failing
  against the removed one.
- **A friendly "page not found" screen.** Visiting a URL that doesn't exist now
  shows a proper, on-brand 404 page with a clear message and buttons to go Home or
  go back — instead of an unfinished placeholder.

### Security

- **Force logout now ends connected app sessions too.** When an admin forces a
  user to log out, any linked application is signed out immediately as well —
  previously a connected app could keep refreshing its own access after a force
  logout. The admin panel's "log everyone out" action does the same across all
  users at once.
- **Closed a timing gap where a connected app could survive being logged out.**
  If a session was invalidated (force logout, password change, or account
  deactivation) at the exact moment a connected app was refreshing its access,
  the app could previously slip through and keep a working session. Refreshes and
  invalidations are now serialized so the invalidation always wins.
- **Login timing no longer reveals whether an account exists.** Login now takes the same amount of time whether or not an account exists, so a failed sign-in no longer reveals which email addresses or usernames are registered.
- **Rate limits can't be bypassed behind the proxy.** Closed a gap where an attacker behind our proxy could dodge the login and password-reset rate limits by rotating a forged forwarding header. Those protections now always key on the real client address.

## [2.0.1] — 2026-07-15

### Security

- **Session-sensitive account fields now require a live browser session.** Email, password, and recovery-PIN changes (and API-key minting) can no longer be driven by an API key alone — they demand the stronger login context.
- **Cross-tenant hardening pass.** WebSocket connections are no longer discoverable across tenants, task references are verified to belong to your tenant before use, and hosted SaaS pins the Host header against origin spoofing.
- **Log and telemetry hygiene.** Lifecycle tokens no longer appear in access logs; error reporting scrubs transactions, query strings, and local variables; and token masking gained a sanitize barrier that closes the remaining public CodeQL log-injection findings.
- **Password checks fail closed** if the hashing backend misbehaves, instead of falling through.
- **CI security-tooling floors raised** — semgrep ≥1.169, pip-audit ≥2.10.

### Changed

- **Backups and exports are now schema-driven.** Account backups, checkpoints, and the GDPR data export derive their coverage automatically from the database schema — new features are captured in backups by construction, and a CI guard fails the build if any table is ever neither captured nor deliberately excluded. Backup files are version-stamped, and older backup files restore cleanly.
- **Message Hub tabs renamed:** "Project Comms" is now **Project threads** and "Town Square" is now **General threads**.
- **Dependency refresh:** FastAPI 0.139, MCP SDK 1.28, Vite 8.1.4, Vuetify 4.1.5, dompurify, marked, eslint, prettier, Sentry SDKs, and js-yaml 5.

### Fixed

- **Account restore could fail or silently drop Message Hub data.** Backups now capture hub threads, participants, and read state; restores of current accounts work again, and older backup files restore with every message kept.
- **The "Messages Waiting" badge is back on the implementation page** — lost in the Message Hub migration — and now updates live as agents receive and read messages.
- **Signed-in sessions no longer hang after a failed token refresh**; all queued requests settle cleanly and you land on the login page.
- **Project closeout could deadlock** when an orchestrator was never staged; force-close now frees it, and all-complete states route to closeout.
- **MCP tool errors fixed:** `list_tasks` with `due_before`, `update_task` with `due_date`, `get_context` with a string depth, and password-reset flows during partial test runs no longer return internal errors.
- **Passwords longer than 72 bytes are rejected with a clear message** instead of a server error.
- **The Admin/Owner badge no longer displays on hosted SaaS** (meaningless on single-user accounts).
- **The frontend test suite runs clean on Windows checkouts under Node 24.**

## [2.0.0.2] — 2026-07-14

### Security

- **Log-forging protection completed across the backend.** Every place where user- or agent-supplied text reaches a log line now strips newline and control characters, so nobody can forge fake log entries. This finishes a convention already present in about half the codebase and closes the CodeQL log-injection findings from the public security audit.
- **The public health endpoint no longer reveals internal error details.** During a database or cache outage, anonymous callers of `/health` now see a generic status; full diagnostic detail moved to the server logs and the authenticated system-status endpoint.
- **Startup lock file is now readable by its owner only**, preventing other local users on a shared machine from interfering with startup coordination.

### Fixed

- **Vision-document import tuned for accuracy.** Rewritten extraction prompting and roundtrip fixes make importing a vision document produce cleaner, more faithful results.
- **Vision-analysis wizard no longer gets stuck on "Analyzing".** A polling fallback and a hardened completion path keep the wizard moving even if a realtime update is missed.
- **Vision analysis now fills in the Codebase Folder automatically** when it can determine the project path, with a user-visible way to skip it.
- **Quieter dev server output.** Dropped a harmless "config.yaml not found" log line that appeared on every normal start.

### Removed

- **Operator-only dev tools no longer ship in Community Edition.** The `dev_tools/` utilities (internal control panel and reset scripts) were operator tooling, not product features.

## [2.0.0.1] — 2026-07-13

### Fixed

- **Installer no longer fails on non-UTF-8 Windows systems.** The generated `.env` template contained typographic characters that, on machines using a legacy locale (e.g. Windows-1252), were written as bytes the installer could not read back — the very first setup step crashed with a decode error. All installer-generated files are now written explicitly as UTF-8 and the `.env` template is pure ASCII, so installs behave identically on every locale.

## [2.0.0] — 2026-07-13

### Added

- **Chain projects — link projects and run them back to back.** Select several projects, link them into a chain with a shared chain mission, and a dedicated conductor stages each one, launches it, watches progress, and advances to the next as each completes. Per-project review checkpoints and a firm human-in-the-loop halt before implementation keep you in control, and the Jobs view follows the whole run live.
- **Work from chat-based AI tools and web coding agents — not just terminal CLIs.** The server now identifies the connected AI tool on every connection and adapts its instructions to what that tool can actually do (terminals, file access, subagents); web coding agents can hand work across pull requests, and setup gained presets for Antigravity, Codex, and generic MCP clients.
- **Message Hub — a built-in messaging center for you and your agents.** Conversation threads bind to projects and jobs, agents post under their own identity with user and agent messages rendered distinctly, and the Jobs view opens each job's thread directly. Agent coordination now flows through server threads instead of local handoff files.
- **Sign in with Google or GitHub.** New Solo accounts can sign up and log in with a Google or GitHub account — no password to remember. Existing password accounts can connect a provider from **Settings → Connected Accounts**, and a provider-linked account can add a password at any time.
- **Fully self-service Solo subscriptions (SaaS).** Subscribe monthly or yearly from the dashboard through a secure embedded checkout, switch plans, cancel or resume, and open your billing portal for invoices and receipts; payment failures and cancellations now trigger clear lifecycle emails. Signup records your acceptance of the Terms, and you are asked to re-accept when they materially change.
- **Roadmap pane.** A dedicated view that keeps upcoming work ordered — agents maintain it as they plan, you can edit and reorder entries, and the Projects list can sort in roadmap order.
- **Search your 360 memory.** A new Memory browser with full-text search across cross-session learnings, plus a `search_memory` tool so agents can look up prior learnings mid-run.
- **Trash and recover.** Deleted threads, tasks, vision documents, and agent templates now land in a recoverable trash with scheduled purge instead of vanishing. Separately, hiding a project is now called **Archived**, and search can find archived projects and tasks.
- **Account backups and restore (SaaS).** Nightly encrypted snapshots to durable storage, plus Danger Zone controls to download your latest backup, create a restore point on demand, or request a restore — and restores preserve your API keys so integrations keep working.
- **Complete, automated account deletion (SaaS).** Deleting your account now auto-cancels an active subscription, offers an immediate-deletion option, and purges everything including backups; dormant deletion requests get a warning at 11 months and are fully removed after a year, with hash-verified deletion receipts retained for compliance.
- **Public status page (SaaS).** Service health and incident history are now published on a public status page linked from the app footer.
- **New agent tools and supervision controls.** Agents gained `stage_project`, `implement_project`, `launch_implementation`, `start_chain_run`, `diagnose_project_state`, and `search_memory`; server-enforced tool profiles (core/standard/full) bound what each connection may call. On the dashboard, you can now request automatic agent check-ins on an interval and tune the silence threshold in Settings.
- **Manage your own credentials.** Change your password and recovery PIN from your profile (recovery PIN: Community Edition), and hosted accounts can change their sign-in email with confirm-before-switch verification and notifications to both addresses (SaaS).

### Changed

- **Execution modes simplified.** Six overlapping execution modes collapsed to two, with the right harness resolved automatically at runtime from the connected tool and shown as a read-only "detected" chip. Headless running is now an explicit account-level toggle, implementation launches default to a human-in-the-loop gate, and the dashboard auto-follows a headless run live in the Jobs pane.
- **Product creation is AI-first.** Attach one or more vision documents and run vision analysis to fill in the product profile — analysis is now the default path (with a create-blank escape), documents are stored in the database instead of by file path, and completing analysis is what unlocks staging.
- **Simpler self-hosted install — Community Edition now runs over plain HTTP.** The installer no longer asks you to choose HTTP vs HTTPS or set up certificates; localhost and LAN installs serve plain HTTP out of the box. HTTPS is now an optional, post-install upgrade you turn on in **Settings → Network** by providing your own certificate. A public/WAN install prints a clear cleartext warning instead of forcing a certificate.
- **Faster dashboard and API across the board.** Project lists paginate, filter, search, and sort in SQL; the frontend dedupes requests and pauses background polling in hidden tabs; hot backend paths (auth hashing, email sends, exports) moved off the event loop; repeated-query hotspots were batched and indexed; and connected AI tools receive much smaller instruction payloads per call. Long sessions and large workspaces feel it most.
- **Refreshed look and feel.** The UI moved to Vuetify 4 / Material Design 3, the four top banners unified onto one accessible style, agent colors are driven by design tokens everywhere, Tools → Connect and onboarding were redesigned, and the Projects list gained a compact view.
- **Connecting AI tools is clearer.** Guided per-tool connect flows with copy-ready snippets, an OAuth-first connect step during first run on hosted accounts (SaaS), a streamlined API-key flow for Community Edition, working CLI OAuth sign-in via loopback redirect, and stay-signed-in through rotating refresh tokens.
- **The notification bell is now database-backed.** Notifications persist across sessions and devices, project notifications deep-link to the project, and previously scattered banners consolidated onto one notification service — including API-key expiry reminders.
- **The in-app user guide covers the whole product.** Expanded to full end-user coverage and made edition-aware, so Community Edition and hosted users each see the chapters that apply to them.
- **Network settings show the real server address.** The Admin → Network tab lists the actual IP(s) and port your server responds on, with a one-step bring-your-own-certificate flow; the certificate how-to moved into the in-app guide.
- **Minimum PostgreSQL is now 16 (18 recommended) (Community Edition).** Installs on PostgreSQL versions 14 or 15 should upgrade the database server before updating.
- **Projects can be marked superseded** with a link to their successor, keeping history navigable without deleting anything.

### Fixed

- **Live updates are far more resilient.** Fixed a WebSocket reconnect storm and a cold-start realtime outage, added heartbeat supervision and per-tenant fan-out isolation, reconnect now re-arms when your machine wakes or comes back online, and the MCP transport was hardened against repeated-request storms and oversized payloads from connected clients.
- **Dashboard navigation no longer stalls,** and after a server update the app recovers from stale cached assets on its own instead of erroring until a hard refresh.
- **Serial numbers stopped jumping to five digits.** The counter no longer counts soft-deleted rows, and historical oversized serials are tolerated instead of erroring.
- **Stuck projects can always be recovered.** Deactivate now resets a never-launched orchestrator, unstage/re-stage releases the execution-mode lock and clears the stale mission, promoting a task to a project no longer deactivates your active project, and refreshing agent templates preserves your edits (reset restores the shipped defaults).
- **Installer and first-run hardening on every platform.** Re-running the installer is now safe and idempotent with a new `--repair` mode and unattended option; installs extract atomically and pin dependencies to the shipped versions; Windows fixes cover PATH refresh and store-alias/prompt hangs; Linux waits out apt locks and guards WSL paths (including browser auto-open); fresh-install defects in taxonomy seeding and first-admin creation were fixed; and the Cookie Domain Whitelist setting is now actually enforced.
- **The landing page's "Forgot your password?" link works again (SaaS).** It previously dead-ended instead of opening the reset flow.

### Security

- **Credential changes now end live sessions.** Changing or resetting a password — including the first-login password set — evicts all live sessions and refresh tokens, deactivating an account closes its WebSockets immediately, a server-side revocation epoch supports forced logout, and access tokens rotate on refresh.
- **Stronger sign-in and credential protection.** Per-account login lockout, failed-auth throttling on the API-key and WebSocket paths, a higher password-hashing cost, and uniform auth errors that do not reveal whether an account exists. New API keys use a stronger storage format, the key-count cap was removed, and expiring keys trigger bell reminders.
- **Tenant isolation enforced in depth.** Bulk updates and deletes now pass through the tenant guard automatically, tenant-scoped models are registration-checked at boot and fail loudly if wiring is missing, MCP tool authorization fails closed, and a permanent cross-tenant isolation test gate runs in CI.
- **Boundary validation and rate limiting hardened.** Agent-supplied input is validated at the MCP boundary with sanitized error responses, structured JSONB payloads are validated at every write, the rate limiter is atomic under concurrency and proxy-aware, and OAuth token-endpoint errors now conform to RFC 6749.
- **Dependency refresh across the stack.** Backend framework pins cleared known CVEs, all high-severity npm advisories were resolved, and routine frontend and backend dependency bumps landed throughout the window.

### Removed

- **Built-in statistical summarizer removed.** Document and memory summaries are now produced by your connected AI agent instead of a bundled algorithm — better summaries and a lighter install (the sumy/NLTK dependency chain is gone).
- **Separate demo edition retired.** Its landing page and flows were folded into the hosted Solo tier; the only editions are Community Edition and hosted SaaS.
- **Built-in certificate generation removed from the installer.** GiljoAI no longer installs mkcert or generates certificates during setup — bring your own (a public CA, your organization's CA, or a local tool such as mkcert) and add it in Settings → Network. This removes the install-time certificate step, the LAN/WAN HTTPS prompt, and the automatic certificate refresh on IP changes.
- **Dead weight deleted.** Dozens of unused REST routes, three low-value MCP tools, retired setup-wizard remnants, and the old OpenClaw preset (superseded by the Antigravity/Codex/generic MCP presets) were removed.

## [1.3.0] — 2026-05-20

### Added

- **Working-time on every agent job.** See at a glance how long each agent has been actively working — live, on the agent card.
- **Native spellcheck across the dashboard.** Project descriptions, missions, and message composition now use your browser's spellcheck.
- **Roomier 360-memory summaries.** Per-entry summary cap raised from 500 to 1,500 characters so longer cross-session learnings survive intact.
- **Customize-prompt panel reordered.** The customize box now sits above the copy button, and your custom text is included in what gets copied.

### Changed

- **Cleaner staging-to-implementation handoff.** When staging finishes, your project sits in a clear *Waiting* state until you click Implement — no flicker, no stale labels, no premature closeout prompts. The implementation kicks off the instant you decide, and the dashboard reflects every transition live.
- **Smoother orchestrator behavior across phases.** One orchestrator per project, transitioning cleanly Working → Waiting → Working → Complete. Replaces an earlier scheme that left phantom rows and confusing statuses.
- **Sharper AI-agent integration.** AI tools connected through MCP get clearer guidance, lighter payloads on routine calls, and cache-aware reads. Day-to-day result: faster, less chatty agent interactions.
- **Projects sorted newest-first by default.** What you most recently touched leads the list.
- **Correct license badge.** README now correctly reads Elastic License 2.0.

### Fixed

- **Closeout button now appears where it should** on implementation-phase projects.
- **Live message-audit modal.** Statuses update in real time instead of freezing at the moment the modal was opened.
- **Cancel popup copy** no longer misleads about hidden projects.
- **Project-open clicks** only fire on the Serial badge, not stray elsewhere on the row.
- **Hidden tasks** no longer leak into the Tasks view.
- **Date filters on project lookups** stopped crashing on certain time-zone edge cases.
- **Setup wizard API-key copy hint** describes what the key is actually for.
- **Codex setup template** escapes special characters safely.
- **Quieter server log.** Heartbeat noise no longer pollutes stdout.
- **Closeout spinner stays visible** during normal memory-write retries instead of flashing transient errors.

### Security

- **Frontend dependencies refreshed:** `dompurify`, `marked`, `axios`, `@sentry/vite-plugin`.
- **Python dependencies refreshed:** `sentry-sdk`, `resend`.

### Removed

- **Legacy `action_required` deprecation fully retired.** Agents that still emit the old tag now get a clear validation error instead of a silent warning.
- **A handful of unused columns and obsolete tests** pruned during the orchestrator refactor.

## [1.2.5] — 2026-05-10

### Added

- **Connect Claude.ai and ChatGPT to your GiljoAI workspace.** Hosted GiljoAI now supports Claude.ai's Custom Connector and ChatGPT's MCP connector. Sign in once through your AI tool of choice and it can orchestrate full development teams through your GiljoAI account — staging projects, launching specialist agents, reading status, and pausing for your input. Built on OAuth 2.1 with full MCP specification conformance.
- **Claude Desktop integration for self-hosted installations.** Self-hosted and localhost installations can be wired to Claude Desktop directly via JSON configuration — no public DNS or HTTPS exposure required. The Setup Wizard generates copy-paste-ready snippets for every supported AI tool.
- **Agents can pause for explicit user approval mid-job.** Long-running specialist agents can now request explicit decisions — "should I proceed with this destructive migration?", "which of these three branches should I implement?" — and the dashboard surfaces the request with the agent's reasoning and clear option buttons. Agents auto-resume the instant you decide.
- **Task management at parity with projects.** Tasks now have the same agent-tool surface as projects: create, update, list, complete, and fetch context through the same agent-friendly tools.
- **Cleaner dashboard payloads.** Project lists now support four projection modes — `triage`, `planning`, `audit`, `forensic`. Default mode cuts payload size by roughly 60% for routine status checks while still surfacing what the user needs at a glance.
- **Optional error tracking.** Self-hosted deployments can opt in to Sentry-based error telemetry by setting a single environment variable. Personally identifying information is scrubbed automatically; team scoping is preserved.
- **Server capability discovery.** A new well-known endpoint declares which MCP specification versions GiljoAI supports plus high-level capability flags. AI tools can negotiate features automatically without out-of-band coordination.
- **Privacy and Terms pages on every install.** First-party privacy policy and terms-of-service pages now ship with every installation, routed cleanly through the Setup Wizard. Improved screen-reader announcements on critical dialogs.

### Changed

- **License switched to Elastic License 2.0.** GiljoAI's source-available license is now ELv2, replacing the prior GiljoAI Community License. ELv2 is a well-established license recognized by legal teams worldwide: it permits internal and commercial use, and only restricts managed-service redistribution and license-key tampering.
- **Faster, calmer dashboard for long sessions.** Background polling was tuned to refresh every 30 seconds (down from every 5) where it was previously running too aggressively. Active operations — job status, agent transitions — still update in real time via WebSocket.
- **Agent handoff prose refreshed.** Built-in agent instructions for handing off to humans are now clearer, more delegated-authority oriented, and aligned with the new approval primitive instead of legacy "blocked" semantics.

### Fixed

- **Toast notification clarity.** Copy-prompt confirmations now describe what the prompt will *do* once pasted — e.g., "Implementation prompt copied. 5 jobs ready to launch." — instead of generic "copied to clipboard" boilerplate.
- **Notification duration slider now controls timeout.** The Settings → Notifications duration slider was wired to the store but had no effect on actual toast timing. Fixed; the slider now reflects your preference for every toast type.
- **Auto-fill next serial number in Create Project dialog.** The serial field now suggests the next available number for the chosen project type instead of leaving it blank.
- **Migration runner no longer stamps backward on restart.** The startup migration check was previously moving the database version pointer backward under certain conditions, causing migrations to replay against already-applied schema and crash. The check now correctly recognizes the modern revision set.
- **Production restarts no longer rewrite the lockfile.** The startup script now uses a read-only npm install path so `package-lock.json` is no longer silently mutated on restart. Prevents lockfile drift on test-server restarts.

### Security

- **Hardened authentication and revocation pathways.** Token lookups and refresh flows now bind on additional identifiers at the query layer, providing defense-in-depth on top of existing tenant isolation.
- **Per-session token revocation.** Issued access tokens can be revoked individually without invalidating the broader user session; revocation propagates to all protected resources within seconds.
- **Stricter audience binding on agent tokens. ⚠ BREAKING.** Tokens presented to the agent-tool boundary must now carry an explicit audience claim. Legacy compatibility for unbound tokens has been removed. Clients holding older tokens must re-authenticate to obtain a properly bound replacement.
- **Improved leak prevention for public-facing files.** New build-time check blocks accidental exposure of internal-network references in public-bound documentation.

### Removed

- **Legacy "blocked" status as a human-in-the-loop signal.** The old pattern of agents setting their own status to "blocked" to request user input is replaced by the proper approval primitive. Self-set "blocked" status is now reserved for genuine error conditions only.

## [1.2.4] — 2026-05-03

### Added

- **Pluggable SMTP email provider.** New `EMAIL_BACKEND` config switch routes transactional email through any SMTP server.

### Changed

- **BREAKING — minimum Python raised to 3.12.** `pyproject.toml` `requires-python` bumped from `>=3.10` to `>=3.12`. `pip install` on pre-3.12 Python now fails with a `requires-python` resolver error. CI, installer scripts, and docs already required 3.12; this aligns the wheel-build constraint with the existing floor.
- **Ruff lint target raised to py312.** Lint sweep auto-fixed PEP 604 unions, walrus opportunities, datetime-aware constructions, and ~60 other modernization sites; remaining warnings either fixed manually or carry justified `# noqa` markers.
- **CI restructured into fast and slow tiers.** Fast checks (lint, secret scan, AI-signature block, pytest, frontend lint+build, vitest) run on every push and PR; the slower installer-integrity matrix runs only on tag pushes matching `v*`.
- **Project tracking migrated into the MCP server.** New work goes through the `create_project` and `write_360_memory` MCP tools rather than the legacy markdown handover files.

### Fixed

- **Dashboard project list returned stale status values.** The `list_projects` tool now correctly filters across all six project statuses, and a project that changes status reflects in the list within one poll cycle. Regression tests added.
- **`create_project` MCP tool: type validation restored.** Unknown `project_type` values now raise `ValidationError` with the structured `valid_types` list (abbreviation, label, color) in the error context. Omitted `project_type` returns the same hint in the success response.
- **System-update banner copy.** Bell-icon notification dropped the redundant "re-run `/giljo_setup`" line (the skills-drift banner already covers that). Both the bell notification and the dashboard update banner now say "restart your server" instead of the older `python update.py` wording.

### Removed

- **Deprecated `deploy_lan_windows.ps1` script.** Pre-unified-installer artifact (2025-10) fully obsoleted by the current `install.ps1` flow.

## [1.2.3] — 2026-05-03

### Security

- **Removed default password fallback in user creation.** `UserService.create_user` no longer silently substitutes a literal default when no password is supplied. The admin endpoint now forwards the user-provided password, and the service treats the absence of a password as an explicit error.

### Changed

- **Skills-version drift banner simplified.** Replaces the previous per-user tracking model. The earlier design tracked three pieces of state for what is fundamentally one comparison: "did the bundled `SKILLS_VERSION` move past the version we last announced?" The new endpoint `/api/notifications/check-skills-version` returns `{current, announced, drift_detected, message}` with no per-user state. Per-version dismissal continues via localStorage. Banner switched from informational blue to brand-yellow warning for better contrast and semantic correctness. The 30-day post-login reminder loop was dropped. Edition-aware copy: CE says "run `/giljo_setup` then `git pull`"; demo/saas says just "run `/giljo_setup`".

## [1.2.2] — 2026-05-01

### Added

- **Project status as a typed enum.** Six statuses (`inactive`, `active`, `completed`, `cancelled`, `terminated`, `deleted`) now live in one place — no more drift between backend services, frontend stores, and database CHECK constraints.
- **New REST endpoint `GET /api/v1/project-statuses/`** exposes the canonical list with labels, color tokens, and lifecycle flags. The frontend reads from this, never from a hardcoded array.
- **Version-consistency check (`scripts/check_version_consistency.py`).** `VERSION` is the single source of truth; `pyproject.toml`, `frontend/package.json`, `package-lock.json`, `__init__.py` fallback, and the latest `CHANGELOG.md` entry must all match. Wired into pre-commit and the release pipeline.

### Changed

- **Installers hardened on every supported path.** All four install paths now work on stock systems with no manual prep: Windows `install.ps1` (verified on stock PowerShell 5.1 + Windows 11), Windows `install.py` direct (Node.js auto-installs via `winget` when missing), Linux `install.sh` (verified on stock Ubuntu / Debian / WSL), Linux `install.py` direct (`python3-venv` detection via an actual `ensurepip` probe). The "please restart your shell" banner now only fires on Windows where it is actually needed.
- **`ProjectStatus` enum is backwards compatible.** `ProjectStatus` inherits from `str`, so every existing `project.status == "active"` comparison still works. Callers adopt the enum at their own pace.

### Notes for upgraders

- No database schema rollback path. The status-enum migration is one-way; if you need to back out, restore from a pre-upgrade backup.
- **macOS not validated this release.** The CI smoke matrix runs `install.py` on macOS-latest, but no end-to-end real-box test was performed. Track as a known gap.

## [1.2.1] — 2026-04-30

### Changed

- **BREAKING — `list_projects` MCP tool default behavior.** No longer returns completed or cancelled projects by default. Pass `include_completed=true` to retrieve archived projects. Agents running `list_projects()` with no arguments will now see only active and inactive projects.

### Added

- **New filter parameters on `list_projects`:** `status` (single or comma-separated), `project_type`, `taxonomy_alias_prefix`, `created_after`, `created_before`, `completed_after`, `completed_before`, `include_completed`, and `hidden` (tri-state: `"true"` / `"false"` / `""` for no filter).
- **`hidden` field exposed in every row** regardless of filter. The `hidden` column is a UI declutter flag, not an agent-visibility gate. Agents always see hidden and non-hidden projects alike unless `hidden=true|false` is passed explicitly.

### Notes

- **Legacy backward-compat.** Callers using `status_filter="all"` continue to work; that value implies `include_completed=True` and is honored when the new `status` param is unset.
- **REST endpoint unchanged.** `GET /api/projects/` (used by the dashboard) was not modified — only the MCP-tool-facing path changed.

## [1.2.0] — 2026-04-29

First minor-version release since the v1.1 line, consolidating six weeks of installer hardening, dependency cleanup, and dashboard polish into a single public cut. If you have been running v1.1.9.5, this upgrade is recommended — especially on Windows.

### Fixed

- **Windows install now works on stock PowerShell 5.1.** Earlier Windows installs could fail with cryptic parser errors before reaching the wizard; `install.ps1` is now ASCII-clean and parses correctly under every PowerShell version that ships with Windows 10 / 11.
- **macOS Apple Silicon installs are more resilient.** A new floor on the `greenlet` dependency plus an explicit fail-fast guard prevents long silent hangs that some early Apple Silicon users saw when binary wheels were not yet published for a new Python release.
- **Linux first-run no longer crashes** on the elevation-guidance step. A path edge case that produced `ValueError` on stock Ubuntu has been fixed.

### Changed

- **"Tools → Connect"** replaces the old "Settings → Integrations" naming throughout the dashboard. Same feature, clearer mental model: one place to connect Claude Code, Cursor, and other tooling.
- **Welcome wizard** now offers a starter-template card on step 4 so new users can get to a working agent setup with a single click.
- **Frontend builds now require Node 22** (matching what most current distributions ship by default).
- **Vite line stabilized.** Vite 8 was briefly trialed but pulled back when its new bundler stack proved unstable on macOS and Windows under real installer conditions; the upgrade will return once that stack ships a stable 1.0.

### Added (agent skills bundle v1.1.11)

- **`/gil_add` gained a Read mode**, so you can pull a project's context or status by alias without opening the dashboard. Add mode is unchanged.
- **Faster, cheaper agent context fetches.** Agents now fetch only the context they need rather than pulling the full bundle every time — meaningfully fewer tokens per multi-step run.
- **Cleaner predecessor handling.** Multi-agent handovers now auto-detect whether you are handing off or being handed to, removing a class of "wrong context" agent runs.

### Removed

- **Legacy distribution-tarball scripts.** The hosted installer at `giljo.ai/install.ps1` and `giljo.ai/install.sh` is the only supported install path.

### Notes for upgraders

- Tagged as `v1.2.0-rc.1` first; promoted to `v1.2.0` after a soak window.
- No database schema changes vs v1.1.9.5. Routine `git pull` + restart is sufficient.
- If you are upgrading from v1.1.9.4 or earlier, you will also pick up the security-foundation work that landed in v1.1.9.5 (four-layer secrets defense, hardened CI). No action required.
- The dashboard will show a "skills bundle out of date" banner when you load v1.2.0 for the first time — this is expected. Run `/giljo_setup` (or pull the latest skills via the dashboard) to upgrade your local CLI skills to v1.1.11.

## [1.1.9.5] — 2026-04-29

### Security

- **Multi-layer secrets defense established.** `gitleaks` runs at gitignore, pre-commit, and push-CI stages with a defensive working-tree scan on top.
- **Boundary `gitleaks` gate added to the release pipeline** — last-chance scan before any push.
- **History rewrite:** stripped HAR files containing PII, including 16 version tags.

### Changed

- **Branch-protection ruleset expanded** with required-check coverage on every push and PR.
- **Cross-platform installer smoke matrix** (Ubuntu / Windows / macOS) added to CI — caught a real macOS arm64 `greenlet` regression on first run.

### Removed

- **Bulk branch cleanup:** 19 stale branches deleted per repo (Dependabot and abandoned dev branches).

## [1.1.9.4] — 2026-04-28

### Changed

- **Frontend dependency train.** Bumped `cryptography` to 47 and `numpy` to 2.2.6 (with the summarization library verified against the new numpy). Vite 8 was attempted and reverted (see [1.2.0] notes).

### Fixed

- **Linux installer:** `Path.relative_to` `ValueError` in `display_elevation_guide`.

## [1.1.9.3] and earlier

Earlier release notes are not archived in this changelog. See the public repo Releases page (`https://github.com/giljoai/giljo-hq/releases`) and the git history for prior version detail.

---

[2.0.1]: https://github.com/giljoai/giljo-hq/releases/tag/v2.0.1
[2.0.0.2]: https://github.com/giljoai/giljo-hq/releases/tag/v2.0.0.2
[2.0.0.1]: https://github.com/giljoai/giljo-hq/releases/tag/v2.0.0.1
[2.0.0]: https://github.com/giljoai/giljo-hq/releases/tag/v2.0.0
[1.3.0]: https://github.com/giljoai/giljo-hq/releases/tag/v1.3.0
[1.2.5]: https://github.com/giljoai/giljo-hq/releases/tag/v1.2.5
[1.2.4]: https://github.com/giljoai/giljo-hq/releases/tag/v1.2.4
[1.2.3]: https://github.com/giljoai/giljo-hq/releases/tag/v1.2.3
[1.2.2]: https://github.com/giljoai/giljo-hq/releases/tag/v1.2.2
[1.2.1]: https://github.com/giljoai/giljo-hq/releases/tag/v1.2.1
[1.2.0]: https://github.com/giljoai/giljo-hq/releases/tag/v1.2.0
[1.1.9.5]: https://github.com/giljoai/giljo-hq/releases/tag/v1.1.9.5
[1.1.9.4]: https://github.com/giljoai/giljo-hq/releases/tag/v1.1.9.4
