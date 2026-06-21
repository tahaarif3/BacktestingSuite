import subprocess
import sys
import os

def run_git_command(args):
    """Runs a git command and returns the stdout, or raises an error."""
    result = subprocess.run(["git"] + args, capture_output=True, text=True, check=True)
    return result.stdout.strip()

def main():
    print("Checking git repository status...")
    
    # 1. Verify we are in a git repository
    try:
        run_git_command(["rev-parse", "--is-inside-work-tree"])
    except subprocess.CalledProcessError:
        print("Error: Current directory is not a git repository.")
        sys.exit(1)

    # 2. Check for changes
    status_output = run_git_command(["status", "--porcelain"])
    if not status_output:
        print("No changes detected in the repository. Clean working directory.")
        return

    print("Detected changes:")
    print(status_output)

    # Parse modified files for a descriptive commit message
    lines = status_output.split("\n")
    modified_files = []
    added_files = []
    deleted_files = []
    
    for line in lines:
        if not line.strip():
            continue
        status = line[:2]
        filepath = line[3:]
        if 'M' in status:
            modified_files.append(filepath)
        elif 'A' in status or '??' in status:
            added_files.append(filepath)
        elif 'D' in status:
            deleted_files.append(filepath)

    commit_parts = []
    if modified_files:
        commit_parts.append(f"Modify: {', '.join(modified_files[:3])}" + ("..." if len(modified_files) > 3 else ""))
    if added_files:
        commit_parts.append(f"Add: {', '.join(added_files[:3])}" + ("..." if len(added_files) > 3 else ""))
    if deleted_files:
        commit_parts.append(f"Delete: {', '.join(deleted_files[:3])}" + ("..." if len(deleted_files) > 3 else ""))

    commit_msg = "Auto-commit: " + " | ".join(commit_parts)
    if not commit_parts:
        commit_msg = "Auto-commit: updates to codebase"

    print(f"Staging all changes...")
    run_git_command(["add", "-A"])

    print(f"Committing changes with message: '{commit_msg}'")
    run_git_command(["commit", "-m", commit_msg])

    # Get current branch
    try:
        branch = run_git_command(["rev-parse", "--abbrev-ref", "HEAD"])
    except Exception:
        branch = "main"

    # Get remote url to verify
    try:
        remote_url = run_git_command(["remote", "get-url", "origin"])
        print(f"Remote origin URL: {remote_url}")
    except Exception:
        print("Warning: remote 'origin' not configured. Setting to target repository...")
        run_git_command(["remote", "add", "origin", "https://github.com/tahaarif3/BacktestingSuite"])

    print(f"Pushing changes to remote origin branch '{branch}'...")
    try:
        push_output = run_git_command(["push", "origin", branch])
        print("Successfully committed and pushed changes!")
        if push_output:
            print(push_output)
    except subprocess.CalledProcessError as e:
        print("Failed to push changes to remote repository.")
        print(f"Error stdout: {e.stdout}")
        print(f"Error stderr: {e.stderr}")
        sys.exit(1)

if __name__ == "__main__":
    main()
