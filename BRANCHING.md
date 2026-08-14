# Working across several machines

Several laptops (and agents) commit to this repo at once over the weekend.
These rules exist to stop us losing an hour to a merge conflict at 2am.

## The one rule

**Never commit to `main` directly.** `main` is always demo-ready. If a judge
walked over right now, whatever is on `main` should run.

## Branch names

```
feat/<short-thing>        a feature or idea            feat/adsb-bridge
fix/<short-thing>         a fix                        fix/stale-flicker
spike/<short-thing>       throwaway experiment          spike/protobuf
<machine-or-name>/<thing> when it's machine-specific    craig/laptop-gps
claude/<thing>            agent-generated work          claude/project-setup
```

Keep them short and lowercase. One branch per idea — resist the urge to build
three things on one branch, because then you can't merge any of them until all
three work.

## The loop

```bash
git checkout main
git pull                                # always start from current main
git checkout -b feat/my-thing

# ... work ...

git add -A
git commit -m "add the thing"
git push -u origin feat/my-thing        # first push
git push                                # subsequent
```

**Push early and push often.** A pushed branch survives a dead laptop, a flat
battery, and a venue power cut. An unpushed branch does not. Push even when the
work is half-finished — that's what branches are for.

## Merging into main

When your branch works and `python tak.py selftest` still passes:

```bash
git checkout main
git pull
git merge feat/my-thing
python tak.py selftest                  # confirm main is still healthy
git push
```

Prefer merging small and often over one big merge at the end. If two people
need each other's work, merge through `main` rather than branching off each
other's branches.

If GitHub PRs suit you better, use them — but during a hackathon direct merges
into `main` after a passing selftest are usually faster, and nobody is
reviewing at 3am anyway.

## When you hit a conflict

```bash
git checkout main && git pull
git checkout feat/my-thing
git merge main                          # bring main into YOUR branch first
# fix conflicts here, on your own branch, where breaking things is safe
python tak.py selftest
git checkout main && git merge feat/my-thing
```

Resolving on your branch instead of on `main` means a botched resolution never
takes the demo down.

## What must never be committed

`.gitignore` covers these, but know why:

- `config.ini` — per-machine, everyone points somewhere different
- `certs/`, `*.p12`, `*.pem`, `*.key` — credentials from their data package
- `.idea/`, `__pycache__/`, `.venv/` — noise that conflicts constantly

If you need to share config, edit `config.ini.example`.

## Avoiding collisions on the shared map

Git is only half of it — we also share a TAK map, and two machines emitting the
same CoT `uid` fight over one marker.

- Set `TAK_CALLSIGN` per laptop (`BRIDGE-CRAIG`, `BRIDGE-SAM`).
- Namespace your uids: `craig-drone-01`, not `drone-01`. Every example has a
  `UID_PREFIX` constant at the top for exactly this.
- Testing something noisy? Use the mesh group or a local port instead of the
  venue's server, so you don't spam everyone's screen:
  `python tak.py send --url udp://127.0.0.1:6969`

## If something goes badly wrong

```bash
git stash                       # park local mess
git checkout main && git pull   # get back to something that works
python tak.py selftest          # confirm it does

git log --oneline -20           # find the last good commit
git checkout <sha> -- path/to/file    # recover one file
```

`main` plus a passing selftest is always your way back.
