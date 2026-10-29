# DR-0004: Stage 3 Amendment 2 (post hoc, after run 1)

- **Decided by:** Claude Code during development. Not a PRSWeave agent, and not pre-registered.
- **Date:** 2026-10-29, after all four run-1 agentic experiments had ended.
- **Status:** run 1 stays the primary, pre-registered result. Runs made after this amendment are labelled `run_2` and reported separately as post-hoc.

## What run 1 showed

| Run | Observed | Cause |
|---|---|---|
| A, B, D | Critic FAIL on `V6b_request_phenotype_correspondence` with `retry_allowed: false`, although its own evidence showed requested site = score site = total_body | The Planner sent `fulfils_request` as the string `"true"`. The packet described the argument as `"true/false"`. V6b tested `is True` and treated every V6b failure as non-retryable, so the controller blocked resubmission. All three Planners then requested human review. |
| A, D | Critic FAIL on `V7_claims_supported` for the number `9.77` | V7 accepted only numbers present in the scores CSV. The Planner had copied 9.77 exactly from a logged evidence record, as its instructions said. |
| D | Critic FAIL on V4 (output integrity) and V5 (independent numbers: SYN11 −0.709 vs −0.79) | Correct detection of the injected corruption. |

These are defects in the Critic and controller interface, which Claude Code wrote. They are not Planner errors. The run-1 outcomes were safe (nothing invalid released) but did not complete the task.

## Changes

1. **Controller:** `submit_for_validation` rejects a non-boolean `fulfils_request` at authorization, with the reason "must be a JSON boolean". The action description now says "JSON boolean true or false (not a string)".
2. **Critic V6b:** an actual site mismatch stays non-retryable. When sites correspond but `fulfils_request` is not `true`, the FAIL is retryable.
3. **Critic V7:** a number in the summary is traceable if it appears in the scores artifact or in any tool result logged in the same run.

The following are unchanged: the scorer, the independent scorer, V1–V5 and V6a, the tolerance, the scenarios, the rubric, the Planner instructions (`planner-v1`) and the baselines' logic.

## Tests added

`tests/test_stage3.py`: `test_amendment2_*` (3 tests). The suite now has 31 tests, all passing on Python 3.14.6 and 3.9.6.

## Effect on the comparison

The baselines always submitted a boolean and a number-free summary, so they never exercised either defect. They were rerun under the amended code. The pre-amendment outputs are kept in `results/stage3/baseline_preamendment/`.

## Exact code change

[`0004-amendment2.diff`](0004-amendment2.diff) is a unified diff from the pre-registered code (`a/`) to the amended code (`b/`). Reversing it (`patch -p1 -R`) restores the pre-registered code. With the patch reversed, runs A1, B1 and D1 replay identically, which verifies that the diff is exact.
