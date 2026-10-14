# Mahavishnu post-commit hook diagnostic — 2026-08-11

Captured during mahavishnu cleanup of `.superprofits/` directory typo. The gitignore-add commit was rejected by the post-commit hook with this traceback (output truncated):

```
File "/Users/les/.local/share/uv/python/cpython-3.13.11-macos-x86_64-none/lib/python3.13/subprocess.py", line ?, in run
  ...
TypeError: BaseSettings._settings_restore_init_kwarg_names() missing 1 required positional argument: 'init_state'
```

The full stack-trace (in the mahavishnu index repo subprocess) leads through `dhara.schema` symbols and `oneiric.config.settings`.

Two prerequisites to reproduce:

1. A repo with the `mahavishnu index install-hooks` post-commit hook. The 162-byte hook script is: `mahavishnu index repo --trigger git-event "$(pwd)" &`
1. A `mahavishnu` install where `BaseSettings._settings_restore_init_kwarg_names()` is the up-to-date (post-`init_state`) signature but a downstream caller is calling it without that argument.

Use this doc as the kickoff when diagnosing the failure in a fresh session.

## Reproduce the failure

In any Bodai repo with the mahavishnu hook installed and a clean working tree:

```sh
git commit --allow-empty -m "test: post-commit hook repro"
```

Expect the commit itself to land (`git log` shows the commit) followed by either an error traceback from the hook or a hung shell. The error in this environment looks like:

```
TypeError: BaseSettings._settings_restore_init_kwarg_names() missing 1 required positional argument: 'init_state'
```

## Decide which side regressed: mahavishnu or oneiric

The traceback includes a frame that mentions `oneiric.config.settings` or similar — capture the full traceback first with the `--show-traceback` and verbose flags:

```sh
mahavishnu index repo --trigger git-event "$(pwd)" --verbose --show-traceback 2>&1 | head -200
```

After capturing, look at the failing frame that calls `_settings_restore_init_kwarg_names`. The flow is typically:

1. mahavishnu CLI imports some module that constructs a `BaseSettings`.
1. `BaseSettings.__init__` (or `__init_subclass__`, or some metaclass hook) calls `_settings_restore_init_kwarg_names()` to seed the kwargs it remembers.
1. The signature got a new required parameter (`init_state`, presumably) in a recent oneiric version, but the call site that constructs `BaseSettings` predates that change.

Identify:

- Which oneiric version is installed in the venv (`uv pip show oneiric`).
- The commit in oneiric that added the `init_state` parameter to `_settings_restore_init_kwarg_names`.
- The code in mahavishnu that constructs `BaseSettings` (or its subclasses) — `grep -rn "BaseSettings\|Settings(" mahavishnu/ --include="*.py" | head`.

## Possible fixes (verify with reproducer first)

1. **Pin oneiric** to the last version before the signature change. The exact version depends on when the change landed; check `git log -p` on the `BaseSettings` file in the oneiric repo.
1. **Bump mahavishnu** to pass `init_state=None` (or whatever the new default expects) at every `BaseSettings(...)` call site. Look for: `BaseSettings(`, `Settings(`, or the class-specific construction.
1. **Add `init_state` to the canonical BaseSettings constructor kwargs list** in oneiric (preferred if oneiric is the upstream you'd want to change).

For each candidate fix, the reproducer should run with the staged change and either succeed (TypeError gone) or fail with a different error.

## Hook workaround while diagnosing

If commits are being blocked by the hook and you need to land work in the meantime, use `--no-verify` to skip the post-commit hook:

```sh
git commit --no-verify -m "..."
```

This bypasses the hook entirely. The cost is that the hook's git-event observability won't record your commit until the hook is fixed.

## When this is fixed

After the upstream fix lands and is rolled out, the mahavishnu `.gitignore` change pending in this repo (line 265: `.superprofits/`) should be committed in a follow-up — it's currently unstaged in the working tree.
