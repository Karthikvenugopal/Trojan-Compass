# Ask before recommending

**Required behavior; not yet fully implemented.** A recommendation needs enough
supported information for a relevant search. Asking a question is not the same
as receiving an answer.

## Why premature recommendations happen

The engine returns broad courses/events even without student context. Chat hides
some initial cards, but permits them after an unsure answer, a repeated question,
or a course/event keyword. Empty lists also conflate unanswered questions with
explicitly unavailable information. These shortcuts do not establish relevance.

## Information states

Initialize every student-information value to `None` in a new conversation.
Reconstruct its value and state from the supplied conversation on every request:

| State | Value | Meaning |
| --- | --- | --- |
| Unanswered | `None` | No supported answer. Ask if this search needs it. |
| Provided | Supported value | The student supplied usable information. |
| Unavailable | `None` | The student explicitly does not know or has no information. |
| Declined | `None` | The student explicitly chooses not to answer. |

A nullable value needs a separate state and supporting student statement.
An assistant question alone never establishes an answer. “I have no experience”
is a provided answer with zero experience; “I don't know” is unavailable.
Unknown skills are not missing skills. Completed courses do not prove mastery.

## Readiness rule

Require a usable direction: a stated interest/topic or sufficiently specific goal
or career target. A greeting, major alone, “show courses,” or “I'm not sure” is
insufficient. Clarify ambiguous targets. Require other facts only when they
materially affect this search, such as prerequisites for an advanced course or a
date window essential to an event request. Do not require a career goal or a
complete questionnaire; an experienced student may provide enough in one message.

1. Reconstruct supported facts, answer states and latest explicit corrections.
2. Identify the minimum facts needed. Graph lookups can inform clarification.
3. If a required fact is unanswered, ask one targeted question with approachable
   choices and return `recommendations: []`. Keep clarifying across turns until
   enough usable information exists; turn count never unlocks cards.
4. If required information is unavailable or declined, acknowledge it. Ask about
   another useful basis if possible. Do not repeat answered questions or assume
   the missing information.
5. Search for recommendations only when sufficient supported context remains.
   Otherwise explain the limitation and return no cards.

Knowing information is unavailable establishes that we asked; it does not make
that information usable. Optional unknowns can remain unknown when they do not
prevent a grounded recommendation. If a valid search finds no matches, say the
available data has no supported matches; do not claim USC has no opportunities.

## Synthetic example

- “Hi.” → Ask what interests them; no cards.
- “I don't know.” → Acknowledge unavailable direction; ask whether building,
  helping people or science sounds interesting. No cards yet.
- “Building websites; I have never programmed.” → A usable topic and beginner
  background now exist. Search introductory options; clarify further only if needed.
- Student declines all useful discovery → Explain insufficient information;
  do not invent personalization.

## Privacy and checks

All facts and answer states remain request-local, derived from frontend memory.
No session/profile store, browser storage, transcript logs or provider memory.
[External provider retention remains separate](PROVIDERS.md).

Verify unanswered versus unavailable information, zero versus unknown experience,
declined answers, sufficient first-turn context, corrections, and request isolation.
