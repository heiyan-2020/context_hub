# Phase 1: Category Discovery

The main agent (you) reads a stratified sample of the hub and proposes the
canonical category list.  This phase is NOT a subagent task — you do it
yourself in your own context because category quality depends on holistic
judgment that's hard to delegate.

## Input

- `<hub_root>/_index/cluster-work/sample.md` — written by
  `scripts/sample_corpus.py`.  ~150-200 notes stratified across year ×
  length × tag-presence, each shown with path, date, existing tags, and
  body preview.

## Your task

Read the sample dump.  As you read, jot down candidate category names.
After the read, settle on a final list of **12-18 top-level categories**
satisfying:

1. **Concreteness** — you can name 3-5 representative notes from the sample
   for each category.  If you can't, the category is too abstract; drop or
   merge it.
2. **Balance** — no category should swallow >25% of the sample.  If one
   does, split it into 2-3 sub-categories.  No category <2% of sample;
   merge tiny ones.
3. **Mutual exclusivity** — a typical note should clearly belong to one
   category, not three.  When in doubt, prefer the more specific category.
4. **Surface separability** — even an LLM with no global view should be
   able to tell category from body+tags alone.  Avoid categories that
   require knowing the user's biography to assign.
5. **Existing tags as signal, not answer** — user tags like `area/AI`,
   `Claude`, `思考`, `长线记录/观点演进` carry strong signal.  Use them
   when proposing categories, but design from content, not from tags.

## Output

Write `<hub_root>/_index/cluster-work/categories.yaml`:

```yaml
schema_version: 1
discovered_at: <ISO-8601 timestamp>
sample_size: <number of notes you read>

categories:
  - name: "Auto/<top1>"
    one_liner: <one sentence telling a subagent what notes belong here>
    typical_signals:
      - <tag pattern or keyword cue>
      - <another>
    example_paths:
      - <rel_path from sample>
      - <another>
  - name: "Auto/<top2>"
    ...
```

The `one_liner` and `typical_signals` are critical: every Phase 2
subagent will see them and use them as the spec for category boundaries.
The agent in Phase 2 does NOT see the sample dump — only this file +
its own batch.  So the categories.yaml must be self-contained.

## Naming conventions

- All category paths start with `Auto/`.
- Use mid-dot `·` to combine two related domains in one name when needed:
  `Auto/学习方法·心态`, `Auto/科研·技术`, `Auto/物品·驾考`.
- Names should be ≤ 8 Chinese chars or ≤ 25 ASCII chars.  Be parseable at
  a glance.

## Fallback bucket

Always include `Auto/未分类` as the last category with this one_liner:

```yaml
  - name: "Auto/未分类"
    one_liner: 落入此类的笔记是 Phase 2 subagent 确实无法判定的少数残余。<2% 期望。
    typical_signals:
      - 内容过短或纯链接，没有可分类的线索
      - 含混跨多个类别且无主导特征
```

The aggregate.py script accepts this as a valid sentinel.
