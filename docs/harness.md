# How this was built, with AI agents

*How the work on [Up to you](../README.md) is organised: one person, several AI coding agent
sessions, and the checks that sit between them and the repository. 中文版：[harness.zh-TW.md](harness.zh-TW.md).*

## Why there is a harness

Most of the code in this repository was written by AI coding agents. One person decides what to
build, reads the results and holds the rulings.

An agent that says «done» or «all tests pass» is making a claim. Left alone, it grades its own
work, forgets a rule when the conversation gets long, and can be steered by text it reads. So the
rules that matter are not left to the agents' memory. They are split into three kinds, and this
page says which is which:

- **enforced by code**: something refuses the commit, the push or the request;
- **enforced by procedure**: a written step a person runs, which nothing in code forces;
- **advisory**: written instructions the agents read at the start of a session.

## The roles

Each role is one agent session with its own instructions and its own files. Five run on the
development machine; two more run elsewhere (one on a machine with a graphics card, one for reading
sources). The role files themselves live outside the public tree (private).

| Role | Does | May not |
|---|---|---|
| coordinator | keeps the written log of decisions and hazards; relays the owner's rulings; the only one that pushes | write code, judge a build |
| backend | the API, the pipeline, the database, the tests | grade its own work |
| frontend | the screens and the built pages | grade its own work |
| judge | gates every build and every public text before the owner sees it | write code, edit a doc, run git that changes anything |
| auditor | reads diffs and audits anything that enters from outside (a tool, a script, a skill) | write code, run git that changes anything |

The one person holds four things, before any build: security, privacy, money, and deploys to
production. An agent may recommend one option with its cost; it may not pick.

## What you can open from here

Public: the tests under [`api/tests/`](../api/tests/) (77 Python test files), the model-evaluation skill at
[`.claude/skills/model-eval/`](../.claude/skills/model-eval/SKILL.md), the decisions page at
[`docs/decisions.md`](decisions.md), and the evaluation reports and answer sheets under
[`evaluation/`](../evaluation/).

Private: the commit checks, the role instructions, the full decision log and the hazard register.
Where this page names one of those, it is marked (private), and you are taking that part on
trust.

## What is enforced by code

- **Nine checks run before every commit** (private; a git hook over the staged files). Each one
  refuses the commit on a finding: a credential-shaped string; a file under `app/` that points
  outside it; a character the shipped fonts cannot draw; a user-facing server message or a status
  code the front end does not carry; text in a README picture below readable size, or a number in a
  picture that does not match its source file; a Python error class ruff reports; a hazard number
  out of order or duplicated; a count written in two places that disagrees.
- **One check runs on the commit message** (private): a message on a commit that touches `app/`
  may not carry a role name, a hazard or decision number, or a person's name, because every such
  commit is published with its message.
- **The publish script refuses `--push`** unless the current public sha is typed on the same line
  (private). Added on 2026-10-10, the day after an agent's shell command carried a backtick that ran
  the push without anyone asking for it; the guard came after that push, it did not stop it.
- **The server refuses to start on the wrong schema.** An API process exits when the database is
  not at its head revision or refuses its login ([`api/entrypoint.sh`](../api/entrypoint.sh)).
- **Database grants are tested**, including what each login may not read
  ([`api/tests/test_role_grants.py`](../api/tests/test_role_grants.py)).

## What is enforced by procedure only

- **Before a release**, the full suite including the database tests is run by hand on the candidate
  commit; `main` moves only after that, on the owner's typed confirmation. Nothing in code blocks an
  untested commit from being pushed.
- **Separate judge.** The judge session gates every build and every public page before the owner sees
  it, and the builder never grades itself. This is a rule the sessions follow; no file lock
  enforces it.
- **The log.** Every decision is written with its cost and the option rejected; every failure
  gets a numbered hazard entry with the test that now guards it (private; 109 entries on
  2026-10-13). The public [`docs/decisions.md`](decisions.md) holds the measured ones.

## Three things the process caught

- **A test that was right for eighteen hours.** Part of
  [`api/tests/test_trip_integration.py`](../api/tests/test_trip_integration.py) was written on
  2026-08-19, and a ruling the same day reversed what it asserted. It was red for nineteen days
  until, on 2026-09-07, a new gate made someone run a test that was not on the register. The
  test's comment keeps the story.
- **A registered test, red for three weeks.** A schema change on 2026-09-16 broke the fixture of
  [`api/tests/test_preference_integration.py`](../api/tests/test_preference_integration.py); nobody
  ran it until 2026-10-08. The register guaranteed the test was named, not that it was run. The fix
  touched the test only; the product was unchanged.
- **A delete path the guards did not cover.** The replay test
  ([`api/tests/test_ingest_replay.py`](../api/tests/test_ingest_replay.py), 2026-08-17) found that
  `TRUNCATE … CASCADE` walked through the triggers that refuse a `DELETE`. Migration
  [`0020_truncate_guard`](../api/migrations/versions/0020_truncate_guard.py) closed it the next day,
  and the test now asserts both refusals.

## What is not proven

- **That this shape is better than one agent per task.** The guess: five standing sessions with
  gates between them produce fewer regressions and need fewer owner interventions than one agent
  built per ticket in its own working copy. A trial is written and pre-registered (same tasks, same
  model and effort, blind scoring, counts of regressions, interventions and cost). It would be
  refuted if the single agent scores the same or better at lower cost. It has not run (2026-10-13).
- **Any number for reliability.** There is a hazard register and a decision log, and no measured
  regression rate, change-failure rate or recovery time, and no «before the harness» period to
  compare against.
- **Independence has a limit.** Builder, auditor and judge are separate sessions of the same
  model family, and the tests are written by the same sessions that write the code. The commit
  checks can be bypassed with `git commit --no-verify`, and the check scripts are ordinary files any
  session can edit. What stands between that and the repository is review and the git history.
