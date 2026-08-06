# Licensing & Commercialization Philosophy

## What We Believe

Giljo HQ is built with full source code included because we believe the best developer tools are transparent. We want individual developers and teams to have full access to a powerful agent orchestration system, run it on their own infrastructure, modify it, and build with it.

At the same time, we need the right to build a sustainable business. When someone repackages this software as a hosted or managed service that competes with our own offering, that is a commercial use case, and we want the option to monetize it.

These two goals are not in conflict. Here is how we balance them.

## What You Can Do (Free)

Under the **Elastic License 2.0 (ELv2)**, you can:

- Run the software for yourself, your team, or your company — solo, small team, large enterprise. Zero per-user gates.
- Modify the source code, fork it, redistribute it.
- Build products and services with it. Sell what you build.
- Use it internally to power your own internal tools and workflows.

The Community Edition is the real product. It is not a demo, and it is not feature-gated by user count.

## What You May Not Do (Without a Commercial License)

ELv2 has three core restrictions:

1. **No managed service for others.** You may not provide the software to third parties as a hosted or managed service where you give them access to substantially the features or functionality of the software. (Internal use within your own organization is fine. Reselling our software as your own SaaS is not.)

2. **No license-key tampering.** You may not move, change, disable, or circumvent license-key functionality, or remove functionality protected by a license key.

3. **No removing or obscuring license/copyright notices.** Trademarks (the GiljoAI name, logo, "Community Edition" branding) remain ours.

If you want to do any of these things commercially, contact `sales@giljo.ai` for a Commercial License.

## Why ELv2 (and not MIT/Apache/BSL)

We chose ELv2 because:

- **It protects the actual moat.** Our concern is not "someone runs this in their company" — that's a feature. Our concern is "someone forks this and runs it as a competing managed service." ELv2 directly addresses that.
- **It's lawyer-vetted by Elastic.** We get the legal substance of a custom license without writing or maintaining one.
- **It's widely understood.** Adopted by Elasticsearch, Redis, Sentry (briefly), MariaDB MaxScale. Companies' OSS-policy reviewers recognize it.
- **It does not gate per-user.** Earlier versions of our license (the GiljoAI Community License v1.1, retired 2026-05-07) gated commercial conversion at "two or more users." We retired that because the architecture itself protects what matters: the SaaS code (billing, multi-org UI, trial reaper, deletion reaper, OAuth onboarding) is not in the public CE export. A team running CE internally is welcome to do so.

## How Contributions Work

We welcome contributions — bug fixes, features, documentation, all of it.

When you contribute code back to this repository (via pull request or patch), you are licensing your contribution to GiljoAI LLC under the Elastic License 2.0 with permission to relicense it under additional terms (including commercial agreements with our customers).

What you keep:
- **You can still use your own code** in your other projects. Your contribution to our repository does not strip your right to reuse your own work elsewhere.

What you give us:
- **The right to include your contribution in commercial offerings.** That is the dual-licensing model that lets us offer paid commercial licenses for the "no managed service" restriction.

If that does not work for you, no hard feelings. You are welcome to fork the repository and run it under ELv2 without contributing back.

## The "Community Edition" Brand

The downloadable version of Giljo HQ is branded as the **Community Edition**. This is the full product. It is not limited, locked down, or missing features compared to what we run ourselves on the SaaS side — except that the SaaS-only code (billing, multi-org provisioning, trial lifecycle, deletion lifecycle, OAuth onboarding flows) is not part of the CE distribution.

The branding exists so users know which edition they are running and so we can maintain a clear distinction between the Community Edition and any commercial or hosted offering.

## Summary

| Scenario | Allowed under ELv2? | Cost |
|---|---|---|
| Solo developer building a product | Yes | Free |
| Solo developer running a business | Yes | Free |
| Internal team / company use (any size) | Yes | Free |
| Forking and modifying for own use | Yes | Free |
| Redistributing the software (license + notices intact) | Yes | Free |
| Hosting it as a managed service for third parties | **No** without a Commercial License | Contact us |
| Selling a competing rebranded SaaS built on it | **No** without a Commercial License | Contact us |
| Removing license/copyright notices | **No** | N/A |

**Contact:** sales@giljo.ai
