# PRD: Toran

Tagline: An event planner. Repo and folder: `toran-event-planner`.

PromptWars Virtual, Challenge 5: Celebration & Event Planner.

## Submission
- Deliverables: working prototype, public GitHub repo, deployed link, video demo, LinkedIn post on AI tool usage and architecture.
- Evaluated on code quality, problem statement alignment, security, efficiency, testing, accessibility and Google services usage.
- Only the final submission's score counts. Submit a working slice early as a safety net, then resubmit only from a tagged commit that is green (lint, types, tests, evals) and checked on the live link.

## Problem
Indian celebrations are not one event. A wedding is 4 to 6 functions, each with its own guests, menu, vendors and schedule. Two families fund it and decide it together.
Budgets break: most families set a number before checking any vendor prices, then revise it.
Timelines break: bridal outfits need 4 to 6 months, good mehendi artists book out months ahead. People find out too late.
Plans change: budgets get cut, vendors cancel, guest lists grow, dates move. Existing tools hand over a static checklist and leave the family to redo the math.
On the day, coordination falls back on the family. Nobody knows who is doing what.
Community events (society Ganesh, Diwali, birthdays) have the same problems at smaller scale: contributions, who does what, what to buy.
Existing AI planners are Western, single-ceremony, couple-only checklists with a chatbot on top.

## User
Primary, and the only persona we design, polish and demo for: the family member actually running an Indian wedding (often a sibling or parent, not the couple).
Secondary: a birthday host or a housing society committee. Supported through function templates only, with no separate flows.

## Core idea
Gemini proposes. Deterministic engines verify.
Gemini handles understanding, clarifying questions, ideas, tradeoff options and language.
Plain tested Python handles money, dates and conflicts, and checks every option Gemini proposes before the user sees it. The AI never does the math.

## v1 features (core)
1. **Describe it in one line, answer a few questions.** Free text like "Sister's wedding in Jodhpur, Feb 2027, about 400 guests, 25 lakh budget" becomes a structured event brief. Gemini asks up to 3 clarifying questions, shown as form fields. Gemini extracts raw values ("25", "lakh", "Feb 2027"); engines convert them to rupees and dates.
2. **Multi-function plan.** One event, many functions (haldi, sangeet, muhurtham, reception). Birthdays and community events use the same model with fewer functions. Each function gets a budget slice, vendor checklist and personalized ideas.
3. **Budget what-if.** Change guests, venue tier or a category. Every unlocked line rebalances instantly. Booked or paid items are locked and never move. Overruns flagged before they happen. No LLM call.
4. **Something changed.** The user reports a budget cut, vendor cancellation, guest count change, date move or dropped function. The engine shows the impact (over budget by how much, which tasks are now late). Gemini proposes 2 to 3 fixes from a fixed set of operations. The engine applies each to a copy, discards any that fail, and shows the rest side by side with real numbers. The user picks one. A vendor cancellation adds a "book replacement" task, checked against lead times and flagged at risk when time is short.
5. **Backward timeline.** Event date in, deadlines out, based on real vendor lead times. Flags tasks that are already late as of today, and marks tasks that can no longer meet their lead time as at risk with the earliest feasible date. Export to .ics and Google Calendar links.
6. **Family contribution ledger.** Who pays which line item (bride side, groom side, society members), including splits between sides. Shows pledged, assigned, paid and gap per person.

## Stretch (only after core is tested and deployed)
7. Replacement vendor discovery via Gemini + Google Maps grounding, offered from the vendor cancellation flow. Vendor names and links come from grounding metadata, labelled as discovered, not endorsed, with Google Maps attribution.
8. Day-of run sheet per function: Now / Next, owner names, clash warnings.
9. Telugu and Hindi output for run sheets and checklists.
10. More ideas per function.
11. Read-only share link: plan compressed into the URL fragment, never sent to the server.

## Out of scope
Login and accounts. Payments. Vendor booking. Seating charts. RSVP system. Real-time multi-user editing. Native mobile app. Free-form chatbot. "Explain this number" chat.

## Success
- Live deployed link, works on phone and desktop.
- Every AI screen has a real Gemini path. Fallback is clearly labelled, never silent, and survives reload.
- Engine invariants always hold: line items sum exactly to the budget (to the rupee), no task after event date, no function outside event dates, locked items never change, every option shown to the user passes all invariants.
- Tests, lint, type checks and CI green. axe accessibility scan passes.
- 2 to 3 minute video shows the full flow: one line in, clarifying questions, plan out, budget cut with three real options, pick one, caterer cancels, replacement task flagged at risk, calendar export.
