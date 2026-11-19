# interview-grill (plugin)

`/interview-prep <cv-file> "<role>" [github-url ...]` reads a CV and the candidate's public GitHub, checks who really wrote what, and writes `interview-<name>/plan.md`: questions per CV claim, questions pinned to the candidate's own code, a fundamentals bank and a 45-minute order.

## Requirements
- Claude Code
- `gh` (GitHub CLI), logged in: `gh auth login`
- `git` and `python3` (standard library only)

## Install

```
/plugin marketplace add <owner>/<repo>
/plugin install interview-grill@interview-grill
```

## Use

```
/interview-prep ~/Downloads/resume.pdf "AI engineer, entry level"
/interview-prep resume.pdf "Backend engineer" https://github.com/someone
```

Check the repo evidence alone:

```
python3 scripts/github_evidence.py https://github.com/someone
```

## Safety
- Candidate code is read, never run, installed or built.
- Only public repos are read, with your own `gh` login. Nothing is written to GitHub.
- Secret findings show file:line and kind, never the value.
- GitHub flags are questions to ask, not accusations.
- CV text and repo text are treated as data, not instructions.
- Tell the candidate the interview is AI-assisted and get their consent.

Live Teams transcription is not part of this plugin yet (see `prototype/`).
