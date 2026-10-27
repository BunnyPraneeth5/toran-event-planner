# Problem alignment

How each part of Challenge 5 (Celebration & Event Planner) maps to a feature in Toran, the
code that does it, and the test that proves it. Paths are relative to the repository root.

The challenge asks for a GenAI planner that works within budget, guest and timeline
constraints, adapts when plans change (budget cuts, vendor cancellations), asks clarifying
questions, and offers trade-offs. Toran's answer is one rule: **Gemini proposes, engines
verify.**

## Mapping

### Budget constraints

| What | Feature | Code | Tests |
|---|---|---|---|
| Every rupee of the budget is placed, exactly | Allocation by largest remainder | [app/engines/budget.py](../app/engines/budget.py) `split`, `allocate` | [tests/unit/test_budget.py](../tests/unit/test_budget.py) `test_split_sums_exactly`, `test_allocate_sums_to_total` |
| Unrealistic budgets are flagged before money is spent | Per-plate ranges by city type and setup level | [app/engines/budget.py](../app/engines/budget.py) `realism_warnings`, [app/data/categories.json](../app/data/categories.json) | [tests/unit/test_budget.py](../tests/unit/test_budget.py) `test_realism_flags_thin_catering_against_tier_range`, `test_realism_metro_expects_more` |
| Try a different total, guest count or setup level | What-if sliders, no AI call | [app/engines/budget.py](../app/engines/budget.py) `what_if`, [app/api/budget.py](../app/api/budget.py) | [tests/unit/test_budget.py](../tests/unit/test_budget.py) `test_lower_total_rebalances_and_keeps_locked`, [tests/api/test_whatif.py](../tests/api/test_whatif.py) `test_whatif_keeps_locked_lines_and_uses_no_ai` |
| Booked and paid money never moves | Lines lock when booked or paid | [app/engines/lines.py](../app/engines/lines.py) `update_line` | [tests/unit/test_lines.py](../tests/unit/test_lines.py) `test_booked_line_is_unchanged_by_a_later_what_if`, [tests/unit/test_adapt.py](../tests/unit/test_adapt.py) `test_locked_lines_never_change` |
| Two families paying | Who pays: pledges, payers, splits, balance | [app/engines/ledger.py](../app/engines/ledger.py) | [tests/unit/test_ledger.py](../tests/unit/test_ledger.py) `test_split_equally_gives_exact_rupees`, `test_remove_person_clears_payers_and_task_owners` |

### Guest constraints

| What | Feature | Code | Tests |
|---|---|---|---|
| Each function has its own guest count | Functions with guests and setup level | [app/models/event.py](../app/models/event.py) `Function` | [tests/unit/test_budget.py](../tests/unit/test_budget.py) `test_allocate_splits_per_plate_by_guests_and_tier` |
| More or fewer guests change per-plate costs only | Guest what-if and "guest count changed" | [app/engines/budget.py](../app/engines/budget.py), [app/engines/adapt.py](../app/engines/adapt.py) | [tests/unit/test_budget.py](../tests/unit/test_budget.py) `test_more_guests_scale_per_plate_lines`, [tests/unit/test_adapt.py](../tests/unit/test_adapt.py) `test_more_guests_raise_per_plate_lines_only` |

### Timeline constraints

| What | Feature | Code | Tests |
|---|---|---|---|
| Deadlines counted back from real lead times | Backward timeline | [app/engines/timeline.py](../app/engines/timeline.py) `build_tasks`, [app/data/lead_times.json](../app/data/lead_times.json) | [tests/unit/test_timeline.py](../tests/unit/test_timeline.py) `test_tasks_scheduled_backward_from_function_date`, `test_no_task_due_after_event` |
| Late and at-risk work is flagged, with the earliest realistic date | Task assessment, Action needed list | [app/engines/timeline.py](../app/engines/timeline.py) `assess_tasks` | [tests/unit/test_timeline.py](../tests/unit/test_timeline.py) `test_event_three_weeks_away_marks_long_lead_tasks_at_risk`, `test_late_once_due_date_passes` |
| Deadlines go into the family's calendar | .ics export and Google Calendar links | [app/engines/calendar.py](../app/engines/calendar.py), [app/web/links.py](../app/web/links.py) | [tests/unit/test_calendar.py](../tests/unit/test_calendar.py) `test_one_all_day_event_per_task_and_one_timed_event_per_function`, `test_google_calendar_link_is_an_all_day_event` |

### Adapting when plans change

| What | Feature | Code | Tests |
|---|---|---|---|
| Budget cut | Impact first, then verified fixes | [app/engines/adapt.py](../app/engines/adapt.py) `apply_change`, `verify_option`, `complete_option`; [app/planner.py](../app/planner.py) `adapt_options` | [tests/unit/test_adapt.py](../tests/unit/test_adapt.py) `test_budget_cut_moves_no_lines_and_reports_overrun`, [tests/unit/test_adapt_ai.py](../tests/unit/test_adapt_ai.py) `test_valid_options_are_verified_and_carry_engine_figures` |
| Vendor cancels | Line freed, "book a replacement" task added and checked against lead times | [app/engines/adapt.py](../app/engines/adapt.py) | [tests/unit/test_adapt.py](../tests/unit/test_adapt.py) `test_vendor_cancelled_frees_line_and_adds_replacement_task`, [tests/unit/test_adapt_ai.py](../tests/unit/test_adapt_ai.py) `test_vendor_cancelled_offers_skip_and_simpler_replacement` |
| Date moves, function dropped | Everything shifts or frees; locked lines stay | [app/engines/adapt.py](../app/engines/adapt.py) | [tests/unit/test_adapt.py](../tests/unit/test_adapt.py) `test_date_moved_earlier_flags_tasks`, `test_function_dropped_frees_open_lines_and_keeps_locked_ones` |
| A fix is only applied if it still works | Server re-applies and re-verifies the chosen fix | [app/planner.py](../app/planner.py) `apply_option` | [tests/unit/test_adapt_ai.py](../tests/unit/test_adapt_ai.py) `test_apply_option_refuses_a_tampered_option`, [tests/api/test_routes.py](../tests/api/test_routes.py) `test_apply_never_accepts_a_client_computed_plan` |
| Nothing breaks when the AI is down | Rule-based fixes with a visible banner | [app/engines/adapt.py](../app/engines/adapt.py) `rule_based_options` | [tests/unit/test_adapt_ai.py](../tests/unit/test_adapt_ai.py) `test_ai_failure_gives_rule_based_options_with_banner`, [tests/api/test_adapt_ui.py](../tests/api/test_adapt_ui.py) `test_fallback_options_carry_the_banner` |

### Asking clarifying questions

| What | Feature | Code | Tests |
|---|---|---|---|
| One line in, structured brief out | Intake on the lite model | [app/ai/service.py](../app/ai/service.py) `extract_brief`, [app/planner.py](../app/planner.py) `intake` | [tests/unit/test_intake.py](../tests/unit/test_intake.py) `test_valid_brief_is_ready_and_money_converted_by_engine` |
| Missing facts become questions, never guesses | Missing fields and up to three questions | [app/engines/parse.py](../app/engines/parse.py), [app/planner.py](../app/planner.py) | [tests/unit/test_parse.py](../tests/unit/test_parse.py) `test_missing_day_is_asked_not_guessed`, [tests/unit/test_intake.py](../tests/unit/test_intake.py) `test_hinglish_missing_day_becomes_a_question`, `test_questions_capped_cleaned_and_deduplicated` |
| Not an event, no plan | Friendly prompt instead | [app/planner.py](../app/planner.py) `NOT_EVENT_MESSAGE` | [tests/unit/test_intake.py](../tests/unit/test_intake.py) `test_non_event_gets_friendly_message` |

### Offering trade-offs

| What | Feature | Code | Tests |
|---|---|---|---|
| Up to three different fixes side by side | Options with plain rationale and engine figures | [app/web/templates/partials/options.html](../app/web/templates/partials/options.html) | [tests/api/test_adapt_ui.py](../tests/api/test_adapt_ui.py) `test_budget_cut_shows_impact_then_verified_options` |
| Every number shown comes from the engines | Rationale may not contain digits | [app/planner.py](../app/planner.py) `_rationale` | [tests/unit/test_adapt_ai.py](../tests/unit/test_adapt_ai.py) `test_rationale_with_digits_is_replaced_by_template` |
| A fix that points the right way but falls short is completed, not shown half-done | Engine top-up | [app/engines/adapt.py](../app/engines/adapt.py) `complete_option` | [tests/unit/test_adapt_ai.py](../tests/unit/test_adapt_ai.py) `test_short_option_is_completed_by_the_engine` |

### Indian context

| What | Feature | Code | Tests |
|---|---|---|---|
| Lakh and crore, in and out | Amounts parsed from "25 lakh", shown as "₹25 lakh" | [app/engines/parse.py](../app/engines/parse.py), [app/web/formatting.py](../app/web/formatting.py) | [tests/unit/test_parse.py](../tests/unit/test_parse.py) `test_parse_amount`, [tests/unit/test_formatting.py](../tests/unit/test_formatting.py) |
| Multi-function weddings, birthdays, community festivals | Function templates | [app/data/function_templates.json](../app/data/function_templates.json) | [tests/evals/briefs.json](../tests/evals/briefs.json) replayed by [tests/unit/test_eval_fixtures.py](../tests/unit/test_eval_fixtures.py) |
| Hinglish and regional input | Intake reads mixed language | [app/ai/prompts.py](../app/ai/prompts.py) | [tests/unit/test_intake.py](../tests/unit/test_intake.py) `test_hinglish_missing_day_becomes_a_question`, [tests/unit/test_eval_fixtures.py](../tests/unit/test_eval_fixtures.py) `test_intake_reads_what_the_brief_says` |

The whole journey is also run in a real browser by [e2e/test_smoke.py](../e2e/test_smoke.py)
`test_full_flow`, and on live Gemini by [tests/evals/run_evals.py](../tests/evals/run_evals.py).

## Worked example: a budget cut

The figures below are real engine output for the test plan in
[tests/unit/test_adapt_ai.py](../tests/unit/test_adapt_ai.py), replayed with the recorded
Gemini answer in [tests/fixtures/ai/adapt_valid.json](../tests/fixtures/ai/adapt_valid.json).

1. **The change.** The family says the budget is now ₹20 lakh instead of ₹25 lakh.
2. **The engines measure it first.** [app/engines/adapt.py](../app/engines/adapt.py)
   `apply_change` sets the new total and moves nothing. Impact: the plan commits
   ₹25,00,000 against ₹20,00,000, so it is **over by ₹5,00,000**. If nothing were wrong,
   Gemini would not be called at all.
3. **Gemini proposes.** It sees the change, the measured gap, the open money per category
   and the functions, all fenced as data. It answers in a fixed schema with operations
   only, never rupee amounts. For example: *"Keep the guest list and make the reception
   simpler."* as `change_tier(reception, standard)` plus `scale_category(attire, -50%)`.
4. **The engines verify.** Each proposal is applied to a copy of the plan and checked:
   lines still sum correctly, locked lines unchanged, no task after the event, and the
   overrun actually gone. One proposal, *"Invite fewer people to the reception"*
   (`reduce_guests(reception, 200)` plus a decor cut), pointed the right way but left a
   shortfall, so `complete_option` trimmed the largest categories evenly and said so in the
   rationale. Anything that still failed would have been dropped.
5. **The user sees real figures.** Three options, side by side, each with an engine-computed
   result: committed ₹19,13,871, ₹19,92,253 and ₹19,99,000 against the new ₹20,00,000
   budget, none over, no newly late tasks.
6. **The user picks one, and the server checks again.** `/api/adapt/apply` re-applies the
   change and the chosen operations to the original plan and re-verifies them. A stale or
   edited option is refused instead of applied.

Gemini contributed what it is good at: understanding the situation and suggesting sensible,
human trade-offs in plain words. Every rupee and every date came from tested Python.
