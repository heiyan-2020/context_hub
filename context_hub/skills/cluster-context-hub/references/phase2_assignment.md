# Phase 2: Subagent prompt template (batched assignment)

Used by the main agent to dispatch one subagent per batch via the Task
tool.  Each subagent reads ONE batch + the category list and writes
ONE result file.

The main agent's job per batch: substitute `<HUB_ROOT>` and `<BATCH_FILE>`
+ `<RESULT_FILE>` placeholders, then dispatch with subagent_type
`general-purpose`.

## Prompt template (give this verbatim, after substitution, to the subagent)

```
You are a classifier subagent for the cluster-context-hub skill.

Goal: assign every note in your assigned batch to EXACTLY ONE category
from the agreed list. Do NOT invent new categories. If a note genuinely
has no fit, use the literal sentinel "Auto/未分类" — but use it sparingly
(< 5% of the batch is a reasonable cap).

## Inputs

1. Categories: read <HUB_ROOT>/_index/cluster-work/categories.yaml.
   Each entry has `name`, `one_liner`, `typical_signals`, `example_paths`.
   These are the only valid labels (plus the sentinel "Auto/未分类").

2. Your batch: read <BATCH_FILE>.
   Each note has format:
       ### <rel_path>
       _<date>_ · len=<n> · tags: <tag list>
       <body, inline #tags already stripped, capped to ~600 chars>

## Decision rules

- The note's existing tags carry strong signal. A note tagged
  `area/AI` belongs in the AI/agent cluster unless its body clearly
  says otherwise.
- The body's domain + structure (long reflective paragraph vs.
  short imperative vs. URL fragment) matters as much as keywords.
- Prefer the MORE SPECIFIC category when two fit.
- Multi-topic notes: pick the dominant topic, not a generic catch-all.
- Be DECISIVE. Don't loop or second-guess. The cost of "wrong" is
  small — the user can sed-rewrite the YAML by hand.

## Output

Write <RESULT_FILE> as YAML:

```yaml
batch_id: <NN as it appears in the batch file>
total: <number of notes you assigned>
assignments:
  - path: "<rel_path>"
    category: "Auto/<...>"
  - path: "..."
    category: "..."
  # one entry per note in the batch
```

Use yaml.safe_dump-compatible syntax: paths in double quotes, no trailing
commas.

## Quality checks before exiting

- Every note in the batch has exactly one entry.
- Every category appears in the categories.yaml (or is the sentinel).
- Distribution within this one batch is plausible (no single category
  should dominate >70% of the batch unless the batch is unusually
  homogeneous).

Return a one-line summary of the batch distribution as your final message
(e.g., "batch-03: 思考·哲学 38, 反思·自我 32, ... [10 categories]").
```

## Main-agent dispatch loop

In the main agent's context:

```
batches = sorted(glob(<HUB_ROOT>/_index/cluster-work/batches/batch-*.md))
For each batch:
  result_file = <HUB_ROOT>/_index/cluster-work/results/result-<NN>.yaml
  Task(
    subagent_type="general-purpose",
    description="classify batch <NN>",
    prompt=<the template above with placeholders substituted>,
    run_in_background=True,
  )
```

Dispatch all N batches in a SINGLE message (parallel Task calls).  Wait
for completion notifications, then run `scripts/aggregate.py`.
