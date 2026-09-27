# Graph Schema

The optional graph manifest is JSON. It is an overlay, not a replacement for `SKILL.md`.

```json
{
  "schema_version": 1,
  "skills": [
    {
      "id": "skill-name",
      "parent": "optional-parent-id",
      "confidence": 0.9,
      "domain": "engineering",
      "relations": [
        {
          "type": "requires",
          "target": "other-skill",
          "weight": 1.0,
          "note": "Why this relationship exists"
        }
      ]
    }
  ]
}
```

## Fields

| Field | Type | Required | Meaning |
|---|---:|---:|---|
| `schema_version` | integer | yes | Currently `1` |
| `skills` | array | yes | Entries keyed by skill `name` |
| `id` | string | yes | Must equal a discovered frontmatter `name` |
| `parent` | string/null | no | Single containment or specialization parent |
| `confidence` | number | no | `0.0`–`1.0`; defaults to `1.0` |
| `domain` | string | no | Broad operational facet, not a taxonomy replacement |
| `relations` | array | no | Directed typed edges from this skill |

Relation fields:

| Field | Type | Required | Meaning |
|---|---:|---:|---|
| `type` | string | yes | One of the edge types below |
| `target` | string | yes | Existing skill `name`; self-edges are rejected |
| `weight` | number | no | `0.0`–`1.0`; defaults to `1.0` |
| `note` | string | no | Human rationale; never treated as executable |

## Edge semantics

- `parent`: the source is a narrower specialization or contained capability.
- `composes`: the source orchestrates the target as part of a workflow.
- `requires`: the source cannot complete correctly without the target.
- `validates`: the source checks the target's output or claims.
- `alternative-to`: either skill may serve the role, with different tradeoffs.
- `supersedes`: the source is the current canonical replacement.
- `related-to`: a weak connection; never use as a prerequisite.

Edges are directed. `neighbors` reports both incoming and outgoing edges but preserves direction and relation type.

## Hashtags

Literal hashtags in `SKILL.md` are normalized to lowercase and indexed as facets. Use a small, stable vocabulary:

```markdown
#skill-management #knowledge-management #verification
```

Prefer three to eight high-signal hashtags. Do not encode temporary task status, secrets, full sentences, or rapidly changing release names as tags. Hashtags answer “what topics mention this?”; typed edges answer “how should this be used with that?”

## Authoring rules

1. Start with the execution relationship, not conceptual similarity.
2. Add an edge only when it changes routing, composition, validation, or replacement.
3. Use `parent` for one primary specialization axis; do not force a tree where a graph is more truthful.
4. Keep cycles valid; traversal, not authoring, must be cycle-safe.
5. Use `alternative-to` when choice depends on constraints, not quality.
6. Lower confidence when evidence is indirect.
7. Version meaningful manifest changes and add a regression query.
8. Remove obsolete edges during review instead of accumulating historical noise.
