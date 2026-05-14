# Phase 4: Optional sub-clustering of oversized buckets

After Phase 3 aggregate, run `scripts/audit_distribution.py`.  Any
top-level cluster > 30% of the corpus should be split into sub-clusters
(`Auto/<top>/<sub>`).  This phase recursively applies the Phase 1+2
pattern to ONE bucket at a time.

For each oversized bucket:

## Step A: Build sub-batch

Manually build (or via a small helper) one markdown file at
`<HUB_ROOT>/_index/cluster-work/subcluster-<top>/notes.md` containing all
notes currently labelled `Auto/<top>`.  Format identical to Phase 2 batch:
`### path` + date/tags/body.

## Step B: Sub-discovery subagent

Dispatch ONE subagent with this prompt:

```
You are a sub-clustering subagent for the cluster-context-hub skill.

The top-level cluster "Auto/<TOP>" currently contains <N> notes and is
oversized (>30% of corpus). Propose 3-6 mutually-exclusive sub-clusters
that partition these notes by sub-topic.

Input:
  Read <HUB_ROOT>/_index/cluster-work/subcluster-<TOP>/notes.md.

Constraints on sub-clusters:
  - Each named "Auto/<TOP>/<SUB>"
  - 3-6 sub-clusters total (not more, not fewer)
  - Each sub-cluster covers 15-50% of the bucket
  - Sub-clusters are mutually exclusive and exhaustive: every note in the
    bucket gets exactly one sub-cluster
  - One sub-cluster can be "Auto/<TOP>/其他" for genuine residuals (< 10%)

Output: write <HUB_ROOT>/_index/cluster-work/subcluster-<TOP>/result.yaml

```yaml
parent: "Auto/<TOP>"
sub_categories:
  - name: "Auto/<TOP>/<sub1>"
    one_liner: ...
  - name: "Auto/<TOP>/<sub2>"
    one_liner: ...
  - ...
assignments:
  - path: "<rel_path>"
    category: "Auto/<TOP>/<subN>"
  - ...
```

Be decisive.
```

## Step C: Merge into the main assignments

The main agent re-runs `scripts/aggregate.py` with the sub-clustered
results merged in.  The aggregate script accepts hierarchical labels
(`Auto/<top>/<sub>`) as long as the top-level prefix is in
`categories.yaml`.

To merge: copy the sub-cluster `assignments` into a new file under
`results/result-sub-<top>.yaml` so aggregate picks it up alongside the
Phase 2 batch results.  Note: sub-cluster assignments will override the
plain `Auto/<top>` label for those paths (later read wins; main agent
should delete the original top-level entries for those paths from the
batch results, or simply rebuild with all sub-cluster results AFTER the
Phase 2 results so the aggregate's "first read" precedence picks the more
specific label).

Simpler alternative: skip the override dance.  After Phase 4 finishes,
edit `_index/synthetic_tags.yaml` directly to replace `Auto/<top>` with
`Auto/<top>/<sub>` for the sub-clustered paths.  The YAML is the source
of truth — hand-edits are fine.
