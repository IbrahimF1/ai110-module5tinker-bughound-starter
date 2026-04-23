# BugHound Mini Model Card (Reflection)

---

## 1) What is this system?

**Name:** BugHound
**Purpose:** BugHound is an experimental AI-powered debugging assistant that analyzes Python code snippets, detects potential issues, proposes fixes, and evaluates the risk of those fixes before deciding whether to auto-apply them or defer to human review.

**Intended users:** Students and engineers learning about agentic workflows, AI reliability, and the design of safe autonomous coding tools.

---

## 2) How does it work?

BugHound follows a five-step agentic loop:

1. **PLAN** — The agent initializes a scan plan for the submitted code snippet.
2. **ANALYZE** — The agent detects issues using either heuristic pattern matching (offline) or a Gemini LLM call (online). Heuristics look for `print()` statements, bare `except:` blocks, and `TODO` comments. Gemini performs a broader, model-driven analysis but its output is validated and may fall back to heuristics if parsing fails or issues are invalid.
3. **ACT** — The agent proposes a fix using either heuristic string replacements (e.g., swapping `print(` for `logging.info(`, rewriting bare `except:` to `except Exception as e:`) or an LLM-generated rewrite.
4. **TEST** — The `assess_risk` function scores the proposed fix on a 0–100 scale, checking issue severity, structural changes (removed returns, code shrinkage, over-editing), and assigns a risk level (low / medium / high).
5. **REFLECT** — Based on the risk level and severity of detected issues, the agent decides whether the fix is safe enough to auto-apply (`should_autofix = True`) or whether human review is recommended.

**Heuristics vs Gemini:**
- Heuristic mode runs entirely offline using regex-based pattern matching. It is deterministic, fast, and limited to three known patterns.
- Gemini mode sends the code to the Gemini API with structured prompts that constrain output format (JSON for analysis, raw Python for fixes). The agent validates and normalizes LLM output, falling back to heuristics on any parsing or validation failure.

---

## 3) Inputs and outputs

**Inputs tested:**

| File | Description |
|---|---|
| `cleanish.py` | Clean code using `logging` — no issues expected |
| `print_spam.py` | Multiple `print()` calls — Code Quality issue |
| `flaky_try_except.py` | Bare `except:` block — Reliability issue |
| `mixed_issues.py` | TODO comment + `print()` + bare `except:` — three issue types |
| Empty / comments-only | Edge case — no executable code |

**Outputs observed:**

- **Issue types detected:** Code Quality (print → logging), Reliability (bare except), Maintainability (TODO comments)
- **Fixes proposed:** Heuristic fixer adds `import logging`, replaces `print(` with `logging.info(`, rewrites `except:` to `except Exception as e:` with a comment
- **Risk reports:** Scores range from 0 (no fix produced) to 95 (minimal changes, low severity). Mixed-issues files typically score in the medium range (40–60) due to combined severity deductions.

---

## 4) Reliability and safety rules

### Rule 1: Return statement removal detection
- **What it checks:** If `return` appears in the original code but not in the fixed code, the score is penalized by 30 points.
- **Why it matters:** Removing a return statement almost certainly changes program behavior — functions that previously returned values would now return `None`.
- **False positive:** A fix that replaces `return x` with `yield x` (generator) would be penalized even though the change is intentional.
- **False negative:** If the LLM replaces `return x + 1` with `return x + 2`, the return keyword is preserved but the behavior changed — this rule would not catch it.

### Rule 2: High-severity blocks auto-fix
- **What it checks:** Even if the risk score ends up in the "low" range (≥75), `should_autofix` is set to `False` when any issue has severity "High".
- **Why it matters:** High-severity issues (e.g., bare except blocks) involve changes to error-handling control flow. These are risky to apply without human verification because they can mask or change error propagation.
- **False positive:** A well-tested, straightforward bare-except rewrite that is perfectly safe would still require manual review.
- **False negative:** A medium-severity issue that involves subtle logic changes (e.g., changing a comparison operator) would still be auto-fixed.

### Rule 3: Over-editing detection (newly added)
- **What it checks:** If the fixed code has more than 150% of the original line count, the score is penalized by 15 points.
- **Why it matters:** LLMs frequently over-edit by adding imports, docstrings, comments, or restructuring code beyond what the issues require. This inflates diffs and increases review burden.
- **False positive:** A fix that legitimately needs to add several lines (e.g., adding proper error handling with logging) would be penalized.
- **False negative:** An LLM could replace every line with different code while keeping the same line count — this rule would not detect semantic over-editing.

---

## 5) Observed failure modes

### Failure 1: Heuristic fixer over-edits print statements
- **Snippet:** `mixed_issues.py` — contains `print("computing...")`
- **What went wrong:** The heuristic fixer adds `import logging` at the top and replaces every `print(` with `logging.info(`. While technically correct, it does not configure the logger, so the output behavior changes silently (format goes from bare text to `INFO:root:computing...`). This is a behavior change that the risk scorer rates as "low" because it only sees low-severity issues and minimal structural change — an unsafe confidence scenario.

### Failure 2: LLM output with invalid severity values
- **Snippet:** Any code analyzed by Gemini
- **What went wrong:** The LLM sometimes returns severity values like `"CRITICAL"`, `"info"`, or `"Warning"` instead of the expected `"High"` / `"Medium"` / `"Low"`. Before the validation guardrail was added, these unknown severities passed through to the risk assessor, which only checks for `"high"`, `"medium"`, `"low"` (lowercase). Unknown severities were effectively invisible to the scorer, meaning high-risk issues could be scored as if they had no severity penalty at all.
- **Fix applied:** Added `_validate_issues()` that normalizes unknown severities to `"Medium"` and filters out issues with empty messages, falling back to heuristics if no valid issues remain.

---

## 6) Heuristic vs Gemini comparison

| Aspect | Heuristic Mode | Gemini Mode |
|---|---|---|
| **Detection scope** | Only 3 patterns: `print(`, bare `except:`, `TODO` | Broader — can detect logic errors, naming issues, missing error handling |
| **Consistency** | Fully deterministic — same input always produces same output | Non-deterministic — temperature and model variation affect results |
| **Fix quality** | Simple string replacement; can break indentation or context | More context-aware rewrites; but may over-edit or change behavior subtly |
| **Risk scoring alignment** | Heuristic fixes are predictable, so risk scores are more reliable | LLM fixes are variable — risk scores may not capture all behavioral changes |
| **Failure mode** | Misses issues outside the 3 hardcoded patterns | May hallucinate issues, return malformed JSON, or produce unusable fixes |

**Key discrepancy:** Heuristic mode consistently catches `print()` and bare `except:` but misses everything else. Gemini catches more issues but sometimes produces fixes that change more than necessary. The risk scorer tends to agree with intuition for heuristic fixes but can be overly permissive for LLM fixes that look structurally similar but semantically differ.

---

## 7) Human-in-the-loop decision

**Scenario:** BugHound should refuse to auto-fix when the proposed fix modifies exception handling or control flow in any way, even if the overall risk score is low.

**Trigger:** The fixed code changes any `try/except/finally` structure compared to the original — detected by comparing the set of exception-handling keywords between original and fixed code.

**Implementation location:** `reliability/risk_assessor.py` — add a structural check that compares exception-handling blocks between original and fixed code, similar to the existing `return` statement check. If `except` appears in the original and the fixed code's `except` lines differ, set `should_autofix = False` and add a reason like "Exception handling was modified — human review required."

**Message to user:** "⚠️ The proposed fix modifies exception handling. This can change how errors propagate. Please review the diff carefully before applying."

---

## 8) Improvement idea

**Improvement: Add a "minimal diff" policy guardrail**

Before accepting an LLM-generated fix, compute a line-level diff between the original and fixed code. If more than 30% of lines changed (excluding whitespace), reject the fix and fall back to heuristics or return the original code with a warning.

**Why this helps:** The most common LLM failure mode is over-editing — rewriting code that did not need to change. A minimal-diff policy directly addresses this by capping how much the fix is allowed to alter. This is low-complexity (a simple diff computation using `difflib`) and measurable (the threshold can be tuned with a test).

**Where to implement:** In `bughound_agent.py`, in the `propose_fix` method, after the LLM returns the fixed code but before returning it. Add a `_is_minimal_diff` helper that computes the change ratio and returns `False` if the threshold is exceeded, triggering a fallback to the heuristic fixer.
