# Master Rules

---

## Project Context And Voice

Project: Automated Investment App
Purpose: Private AI-assisted trading platform scaffold with real-money risk considerations.
Voice: Precise, cautious about claims, and evidence-backed. Never promise profit. Distinguish live trading facts from experiments.
Keep the shared rules below unless this section gives a narrower project-specific direction.

---

## Carlos's Voice (read first)

When writing in Carlos's voice (blog posts, newsletters, client emails, social),
follow the rules below. If Carlos shares real past writing, match its cadence
over any description. The rules:

- **Run-on sentences chained with commas.** Long and flowing is the default. Do
  not clip into short choppy sentences.
- **Straight to the point.** Run-on does not mean meandering. State the point
  fast, no wind-up.
- **Exclamations** where the energy is real.
- **Avoid "and" as a crutch (high priority).** No "and that's why", "and you
  see", "and so", and no long "and ... and ... and" chains. Use commas, or just
  say the next thing. An occasional "and" is fine.
- No em dashes (see below). No "homework"/academia framing, Carlos runs a
  business now, use "study" or "project".

---

## Writing - Phrases and Patterns to Avoid

### Punctuation and Grammar

**Em dashes**
Severity: 5. Do not use em dashes for breaks or emphasis. Replace with commas, periods, or restructure the sentence. Maximum one per 500 words, only for genuine interruptions.

**Ellipses**
Severity: 3. Avoid ellipses for dramatic effect. Use only for actual trailing off or interrupted speech. Never stack them for pause or mood.

**Smart quotes**
Severity: 2. Use straight quotes consistently. Do not use curly/slanted quotes.

---

### Words That Are Banned

Never use: delve, moreover, furthermore, albeit, indeed, certainly.

These words signal academic padding. Cut them or rewrite the sentence without them.

---

### Transition Addiction

Severity: 4. Do not open paragraphs with transition words. "Moreover", "Furthermore", "However", "Nevertheless" - remove them. Let the content flow naturally from one thought to the next without signposting.

---

### Metaphor and Cliche

Severity: 4-5. Do not use:
- "a symphony of" anything
- "a tapestry of" anything
- "a testament to"
- "nestled in"
- "a delicate balance"
- Comparisons that are random or nonsensical - "like an angry octopus after a bad haircut"

Use concrete, specific descriptions instead. Only use a metaphor if it genuinely clarifies meaning.

---

### Phrase Patterns

**"Not X, but Y" constructions**
Severity: 4. Make direct statements. Do not write "it's not just a problem, it's a crisis." Pick one word and commit.

**Rhetorical question-answer pairs**
Severity: 4. Do not write a question and then immediately answer it. "What happened next? Chaos." Choose either the question or the statement, not both.

**Rule of three**
Severity: 5. Do not default to grouping everything in threes. "She was smart, capable, and determined." Vary between single items, pairs, and longer lists. The rule of three is a crutch.

---

### Structural Issues

**Bullet points**
Severity: 4. Do not use bullet points in narrative or conversational writing. Write lists as natural sentences within prose.

**Section headers**
Severity: 3. Do not break responses into labeled sections with headers unless the content is genuinely reference material that someone will navigate. Use natural paragraph flow.

**Preamble openers**
Severity: 3. Do not open with "Let's break it down", "Let's dive in", "Let's dissect this." Start directly with the content.

---

### Stylistic Quirks

**Overly clean prose**
Severity: 4. Avoid academic, over-polished sentences. "The implementation of this solution yields optimal results" sounds like a press release. Write conversationally with personality and varied sentence structures.

**Emphasis overload**
Severity: 3. Do not use bold or italics more than once per 500 words. Rely on word choice and sentence structure to create emphasis, not formatting.

**Dramatic fragments**
Severity: 3. Do not use short fragments to manufacture drama. "It was over. Finally. Completely." Vary sentence length naturally. Do not force tension through structure.

---

### Content Patterns

**Telling instead of showing**
Severity: 4. Do not explain reactions after showing them. "She was angry, which showed in her expression" - cut the explanation. Show it through action and dialogue.

**Redundant adjective pairs**
Severity: 3. Pick one adjective. "Dark and brooding", "loud and brash", "quick and agile" - choose the stronger word and cut the other.

---

### Genre-Specific (Romance / Dialogue)

Avoid clichéd physical gestures: pressing foreheads together, leaning on elbows, "lips swollen with kisses", "blooming like a promise." Find specific, original physical details.

Write dialogue that does not answer itself. If a character asks a question, the response should not be a mirror of the question rephrased.

---

### Master Prompt - Quick Copy

For pasting into any new session:

Write naturally without: em dashes (use commas or periods), the words delve / moreover / furthermore / albeit / indeed, "not X but Y" constructions, rhetorical question-answer pairs, groups of three, bullet points, section headers, excessive emphasis with bold or italics, metaphorical cliches like "symphony of" or "tapestry of", or explanatory phrases like "which was surprising because." Use concrete descriptions, varied sentence structures, and conversational tone with personality.

---

## Code - General Do's and Don'ts

Do write clean, readable code with meaningful variable names. Comment the "why", not the "what". Keep functions small and single-purpose. Use consistent formatting and follow the project's linter and formatter rules. Write for the next developer who reads it, not just for the machine that runs it.

Don't leave dead code or commented-out blocks in production. Don't hard-code secrets, API keys, or environment-specific values - use environment variables. Don't ignore error handling. Don't over-engineer early.

---

## Git and GitHub

Do write clear, descriptive commit messages in present tense: "Add hero section layout", not "added stuff". Use feature branches for all new work. Keep commits focused to one logical change. Review your own diff before pushing.

Don't commit directly to main. Don't push broken code to a shared branch. Don't use vague commit messages like "fix", "update", or "stuff". Don't commit node_modules, .env files, or build artifacts - keep .gitignore clean.

---

## Vercel Deployments

Do store all secrets in Vercel environment variables, never in the codebase. Test locally before pushing to a branch connected to a preview deployment. Use preview deployments to review changes before merging to main. Keep production deploys tied to the main branch only.

Don't store API keys or secrets in your codebase. Don't deploy untested code directly to production. Don't ignore build logs when a deployment fails.

---

## General Development

Do read the full error message before guessing at a fix. Keep dependencies up to date and audit them periodically. Document setup steps in a README so any machine can run the project. Use .env.example to communicate required environment variables without exposing values.

Don't skip the README. Don't install packages you don't understand. Don't ignore console warnings. Don't build features no one asked for yet.

---

This file is a living document. Add to it as new patterns and preferences emerge.
