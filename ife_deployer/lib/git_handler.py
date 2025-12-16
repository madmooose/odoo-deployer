import os
import sys
import git


class GitHandler:
    """Handles Git repository operations such as cloning and fetching updates."""

    def __init__(self, github_org):
        self.github_org = github_org

    def get_repo(self, slug, deployment_folder):
        """Clone the repository if not present, otherwise fetch the latest updates."""
        if not os.path.exists(deployment_folder):
            try:
                repo = git.Repo.clone_from(
                    f"{self.github_org}/{slug}", deployment_folder
                )
                print(f"✅ Cloned repository: {slug}")
            except Exception as e:
                print(f"❌ Error cloning repository: {e}")
                sys.exit(1)
        else:
            try:
                repo = git.Repo(deployment_folder)
                for remote in repo.remotes:
                    remote.fetch()
                print(f"🔄 Fetched latest changes for: {slug}")
            except Exception as e:
                print(f"❌ Failed to fetch repository updates: {e}")
                sys.exit(1)

        return repo

    def get_default_branch(self, repo):
        """Get the default branch of the repository.
        Todo: Check if we go with static production branch naming or config.yaml values.
        Probably later one.
        """
        try:
            default_branch_names = [
                "refs/heads/Pre",
                "refs/heads/live",
                "refs/heads/main",
                "refs/heads/master",
            ]

            repo.remotes.origin.fetch()
            remote_branches = [
                line.split()[1]
                for line in repo.git.ls_remote("--heads", "origin").splitlines()
            ]

            for branch in default_branch_names:
                if branch in remote_branches:
                    repo.git.checkout(branch)
                    repo.git.pull("origin", branch)
                    return branch.split("/")[2]
            # TODO: Find a proper way to get the default branch from GitHub
            # if remote_branches:
            #     default_branch = remote_branches[0].split('/')[-1]
            #     return repo.remotes.origin.refs[default_branch]
            raise ValueError("No default branch found")

        except git.exc.GitCommandError as e:
            print(f"❌ Error: {e}")
            sys.exit(1)

        print("❌ No remote branches found.")
        sys.exit(1)

    def create_feature_branch(self, repo, base_branch, branch_name, description):
        """Create a new feature branch based on the specified base branch."""
        try:
            repo.heads[base_branch].checkout()
            if repo.is_dirty():
                print(
                    f"❌ {description} Repository is dirty. Please commit or stash changes."
                )
                sys.exit(1)
            if branch_name in repo.heads:
                print(
                    f"🔄 {description} branch '{branch_name}' already exists. Deleting it."
                )
                repo.delete_head(branch_name, force=True)

            new_branch = repo.create_head(branch_name, base_branch)
            new_branch.checkout()
            repo.git.push("origin", "--force", branch_name)
            print(
                f"✅ Created and pushed new {description} branch: {branch_name} based on {base_branch}"
            )
        except Exception as e:
            print(f"❌ Error creating feature branch: {e}")
            sys.exit(1)
        return new_branch

    def push(self, repo, task_vals, state, files):
        """Push changes to the remote repository."""

        module_name = task_vals["module_name"]
        if module_name == "*":
            module_name = task_vals["ife_repository"].split("/")[-1]
        try:
            if files:
                repo.git.add(files)
            else:
                repo.git.add(".")
            if state == "added":
                commit_message = f"[{task_vals['id']}][ADD] {module_name}"
            else:
                commit_message = f"[{task_vals['id']}][UPDATE] {module_name}"
            repo.git.commit("-m", commit_message)
            repo.git.push("origin", repo.active_branch.name)
            print(f"✅ Pushed changes to {repo.active_branch.name} branch")
        except Exception as e:
            print(f"❌ Error pushing changes: {e}")
            sys.exit(1)
