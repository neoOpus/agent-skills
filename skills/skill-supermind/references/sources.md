# Sources and Update Policy

## Authoritative implementation sources

### Agent Skills specification

- URL: https://agentskills.io/specification
- Accessed: 2026-09-23
- Used for: directory structure, required frontmatter, name/description constraints, optional directories, progressive disclosure, and relative references.

Key constraints used by this skill:

- `name`: 1–64 characters; lowercase alphanumeric and hyphens; no leading, trailing, or consecutive hyphens.
- `name` must match the parent directory.
- `description`: non-empty and at most 1024 characters.
- recommended `SKILL.md`: under 500 lines and about 5,000 tokens.
- scripts, references, and assets are optional and loaded progressively.

### Agent Skills best practices

- URL: https://agentskills.io/skill-creation/best-practices
- Accessed: 2026-09-23
- Used for: coherent skill scope, progressive disclosure, real-execution refinement, explicit validation loops, defaults, and avoiding instructions the agent already knows.

## Learning-science sources

### The Learning Scientists: six strategies

- URL: https://www.learningscientists.org/blog/2017/4/20-1
- Accessed: 2026-09-23
- Used for: spacing, interleaving, elaborative questioning, concrete examples, dual coding, retrieval practice, and sleep as learning supports.

### Spaced learning, interleaving, and retrieval practice review

- URL: https://pmc.ncbi.nlm.nih.gov/articles/PMC8759977/
- Title: “Quantifying the effect of spaced learning on retention: a meta-analysis”
- Accessed: 2026-09-23
- Use: supporting the general value of spacing while avoiding claims that one fixed schedule fits every learner or topic.

The learning guidance is intentionally conservative. Effective strategies are not magic, may not transfer equally to every domain, and should be evaluated against observable performance.

## Change policy

Review external sources:

- **Quarterly:** check the Agent Skills specification and best practices.
- **Before release:** re-read the specification constraints and run tests.
- **When a source changes:** record the date, changed claim, affected artifact, compatibility decision, and migration note here.
- **On a security or correctness advisory affecting SQLite, Python, or parsing:** patch and test before resuming dependent workflows.

Generated catalog files and SQLite databases are build artifacts, not sources of truth. Never update the index by hand.
