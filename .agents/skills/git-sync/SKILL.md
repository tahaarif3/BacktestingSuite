---
name: git-sync
description: Check the project codebase for changes, create automated commits with descriptive messages listing modified/added/deleted files, and push updates to the remote GitHub repository.
---

# Git Sync Skill

Use this skill when you need to check the codebase for updates, stage modifications, create an automated git commit with a descriptive message, and push to the remote repository.

## Instructions

1. **Verify Git Repository Status**:
   - Run standard git checks (`git status`, `git diff`) or run the included Python helper script:
     [.agents/skills/git-sync/scripts/git_sync.py](file:///C:/Users/bigbo/Spy_Backtest/.agents/skills/git-sync/scripts/git_sync.py)
   - Inspect files that have been updated, added, or deleted.

2. **Run Git Sync**:
   - You can run the automation script using the terminal:
     ```powershell
     python .agents/skills/git-sync/scripts/git_sync.py
     ```
   - Alternatively, perform manual Git commands:
     ```powershell
     git status --porcelain
     git add -A
     git commit -m "Auto-commit: <descriptive message based on changes>"
     git push origin <current-branch>
     ```

3. **Check/Set Remote Origin**:
   - Verify origin is set to `https://github.com/tahaarif3/BacktestingSuite`.
   - If not set or incorrect, configure it:
     ```powershell
     git remote set-url origin https://github.com/tahaarif3/BacktestingSuite
     ```

## Output & Verification
- Report the specific files that were modified, added, or deleted.
- Report the commit hash and confirm that the push to `https://github.com/tahaarif3/BacktestingSuite` was successful.
