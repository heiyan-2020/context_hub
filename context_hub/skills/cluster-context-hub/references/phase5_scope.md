# Phase 5: Author description + routing_scope per Auto/* path

After `aggregate.py` writes `synthetic_tags.yaml`, every `Auto/*` path in
the assignment needs an entry in `<hub_root>/_index/scopes.yaml`.

You can author these yourself in your context (recommended for small N),
or dispatch one subagent per path (recommended for N > 15).

## Output contract (load-bearing)

| field | safe to display to user? | content rule |
|---|---|---|
| `description` | YES | Describe the **collection** ("约 N 篇关于 X 的笔记"). NEVER first-person about the user ("用户认为 / 你倾向"). |
| `routing_scope` | NO (agent-only) | More expressive; can describe what tendencies / threads / themes appear in the bucket; can use "用户倾向 X 的迹象出现" but never quote it back as if it were the user's words. |

The user-facing `INDEX.md` shows `description` only.  `routing_scope`
lands in `tree.json` and is consumed by downstream agents that follow
the cluster-context-hub SKILL.md's "never quote routing_scope verbatim
to user" rule.

## Method A: Author in your own context (recommended, ≤20 paths)

Run `scripts/scaffold_scopes.py --root <HUB_ROOT>`.  It prints every
missing `Auto/*` path plus 3-5 sample notes.  Read each cluster's
samples, then directly write/edit `<hub_root>/_index/scopes.yaml` to add
entries.  Preserve all existing entries.

## Method B: Subagent per path (recommended for N > 15 or sub-clusters)

For each missing `Auto/<path>`, dispatch a subagent with this prompt:

```
You are a scope-authoring subagent for the cluster-context-hub skill.

Read <HUB_ROOT>/_index/cluster-work/scope-input-<SLUG>.md (path
substitutions done by the main agent).  It contains:
  - The cluster path (e.g. "Auto/学习方法·心态")
  - 6 representative sample notes (full body)
  - The cluster's total count and a few other clusters' names for context

Write a YAML block to <HUB_ROOT>/_index/cluster-work/scope-output-<SLUG>.yaml
in this exact format:

  path: "Auto/<...>"
  description: <one-line collection-level description, ≤ 60 chars,
                no first-person about the user>
  routing_scope: |
    <2-3 sentences describing what's in the bucket; agent-only routing
    hint. Acceptable to use phrases like "用户倾向 X 的笔记" or "这些
    笔记多围绕 Y 展开", but NEVER produce a verbatim sentence that
    would mislead a downstream agent into thinking the user wrote it.>

Rules:
- description is shown to humans in INDEX.md. Treat it as a museum
  placard.
- routing_scope is consumed by agents to decide which notes to read.
  Be specific about cluster boundaries and adjacent clusters.
- Do not paraphrase any single note; describe the SHAPE of the collection.
```

After all subagents return, the main agent merges the YAML blocks into
`<hub_root>/_index/scopes.yaml` under the `scopes:` key, preserving all
existing entries.
