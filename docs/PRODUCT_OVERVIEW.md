# Giljo HQ: Product Overview

*Last updated: 2026-07-17*

## What Is Giljo HQ

Giljo HQ, a GiljoAI product, is a context engineering platform for AI-assisted software development. It stores your product knowledge, generates focused prompts, and coordinates your agents through the Model Context Protocol (MCP). It never writes code or reasons about your codebase itself. Your own AI coding tool does that work, using your own subscription.

## Who It Is For

| User | What they get |
|---|---|
| Solo developer using Claude Code, Codex CLI, OpenCode, or any MCP client | Multi-agent workflows without manual prompt engineering |
| Developer building production software across many sessions | Persistent product context and 360 Memory that carry across projects |
| Anyone coordinating a crew of agents | A shared product definition, a ranked roadmap, task boards, and a message hub with an audit trail |

Giljo HQ is for developers who already use AI coding tools and want a structured orchestration layer on top of them.

## Core Value Proposition

Define your product once. Every agent that connects starts with the full picture.

Without GiljoAI, each AI session starts blank. You re-explain your tech stack, constraints, architecture decisions, and prior work each time. GiljoAI solves this by storing that knowledge permanently and injecting it automatically at session start.

The platform also coordinates multi-agent teams. Rather than running one large context window, GiljoAI distributes context to the right agent for each role: an implementer gets code-relevant context, a reviewer gets quality-relevant context, a documenter gets specification context. Each agent gets exactly what it needs for its role.

Giljo HQ sits at the intersection of product thinking and development. Whether you are a developer learning to define what you build before you build it, or a product manager turning a specification into working software, the platform gives you a structured path from vision to execution. The clearer your product definition, the more effective every agent session becomes.

---

## What's Inside

**Your tools, your subscription.** GiljoAI never touches your AI credits. Connect Claude Code, Codex CLI, OpenCode, or any generic MCP client — one at a time or several at once. GiljoAI is a passive MCP server: your tool connects over HTTP, reads context and coordination data, and does all the reasoning and coding itself.

**Products with vision-document context.** A Product holds everything your agents need to know: description, tech stack, architecture, testing strategy, and more. Fill it in by hand, upload a vision document, or point an agent at your codebase and let AI populate the fields for you.

**Projects, tasks, and missions.** Break work into projects (multi-step, agent-run) and tasks (quick notes). Each project gets a mission the orchestrator plans before any code is written, and you watch progress live.

**The Roadmap.** A single ranked plan of your product's upcoming projects and tasks. Your AI agent scores each item for risk and effort; you drag to reorder.

**Chain projects.** Link 2 to 5 projects to run one after another under a single chain mission. A dedicated conductor stages, launches, and advances each one, pausing for your go-ahead before it starts.

**The Message Hub.** Threads where you and your agents talk — Project threads bound to a project, General threads for everything else. Agents post under their own identity; you reply by broadcast or direct message.

**360 Memory.** Every completed project writes a durable memory entry — what was built, key decisions, patterns found — and the next project inherits it. A searchable Memory browser lets you full-text search your whole history.

**Agent templates.** You get 16 active agent slots: 15 custom roles you define plus 1 reserved orchestrator. Edit each one's role and expertise; every agent is handed its own profile by the server the moment it starts work, so an edit applies to the very next agent you launch with nothing to install or sync. A `/giljo` skill lets you create, update, and look up projects and tasks without leaving your session.

**A guided start.** An animated welcome tour introduces the platform after setup and offers four ways to create your first product (see Getting Started).

**Trash and recover.** Deleted projects, tasks, threads, vision documents, and agent templates go to a recoverable trash before they are purged — so a wrong click is never permanent.

## Editions: Community and Hosted

> [!CE]
> **Community Edition** is self-hosted on your own PostgreSQL database — you control updates and your data never leaves your machine. It runs over plain HTTP by default on localhost and your LAN; HTTPS is an opt-in, bring-your-own-certificate upgrade in Settings → Network.

> [!SAAS]
> **Hosted GiljoAI** adds sign-in with Google or GitHub, a self-service Solo subscription, and nightly encrypted backups you can download or restore — all managed for you, nothing to install.

---

## How to Get Started

Once you are signed in, the in-app **Setup Wizard** walks you through four steps: choose your tools, connect each one, install your skills, and launch. An animated welcome tour then opens and helps you create your first product. The **Getting Started** chapter walks through all of it.

> [!CE]
> Self-hosting? Install Giljo HQ first by following [INSTALLATION_GUIDE.md](INSTALLATION_GUIDE.md), then sign in and run the Setup Wizard.
