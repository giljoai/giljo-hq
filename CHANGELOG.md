# Changelog

All notable changes to this project are recorded here. This changelog follows the [Keep a Changelog](https://keepachangelog.com/) convention — entries are grouped by change type (Added / Changed / Fixed / Removed / Security). Versions follow `MAJOR.MINOR.PATCH[.HOTFIX]` and tags live on the public repository (`giljoai/giljo-hq`).

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
- **The installer scripts are now checked for internal network details before every
  release.** The automated scan that keeps private addresses, internal machine names
  and developer folder paths out of the published code was skipping the Windows and
  Linux installers, the first files most people open. They are covered now, and the
  list of covered files is read straight from the packaging step, so a newly published
  script cannot quietly fall outside it.
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
