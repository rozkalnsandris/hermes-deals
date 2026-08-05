# Netto RPi5 shadow audit ownership v2 checklist

- dedicated worktree `.git` pointer matches the exact admin directory;
- `commondir` resolves to `/home/andris/hermes-deals/.git`;
- reverse `gitdir` resolves to the dedicated worktree `.git` file;
- only the dedicated worktree metadata is repaired to `andris:andris`;
- `GIT_OPTIONAL_LOCKS=0` is inherited by the v1 installer;
- final `git status` succeeds as `andris` and is clean;
- final index owner is `andris:andris`;
- production apply remains unauthorized.
