#!/usr/bin/env python3
import click
import os
import sys
import git
import shutil
import subprocess
from subprocess import check_call
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedSeq
from glob import iglob
from dotenv import load_dotenv
from .lib import addons
from .lib.git_handler import GitHandler
from .lib.odoo_client import OdooClient
from .lib.yaml_handler import YAMLHandler

load_dotenv(override=True)
GITHUB_URL = os.getenv("GITHUB_URL")
GITHUB_ORG = os.getenv("GITHUB_ORG")
ODOO_URL = os.getenv("ODOO_URL")
ODOO_DB = os.getenv("ODOO_DB")
ODOO_USER = os.getenv("ODOO_USER")
ODOO_TOKEN = os.getenv("ODOO_TOKEN")
ODOO_STAGE_ACKNOWLEDGE = os.getenv("ODOO_STAGE_ACKNOWLEDGE")
ODOO_TYPE_DEPLOYMENT = os.getenv("ODOO_TYPE_DEPLOYMENT")


@click.group()
def cli():
    """CLI for managing Odoo module deployment."""
    pass


# python odoo-deployer.py create 123 --generate -d project
@cli.command()
@click.argument("task_id", type=int)
@click.option("--generate", is_flag=True, help="Also run generate step after create")
@click.option("-d", "--repo-name", default=None, help="Repository to limit generation")
def create(task_id, generate, repo_name):
    """Fetches ticket information from Odoo task and creates a feature brnach based on that."""
    odoo_client = OdooClient(ODOO_URL, ODOO_DB, ODOO_USER, ODOO_TOKEN)
    git_handler = GitHandler(GITHUB_ORG)
    yaml_handler = YAMLHandler()

    task_vals = odoo_client.get_task(task_id)

    task_id = task_vals["id"]
    module_name = task_vals["module_name"]
    module_repository = task_vals["repository"].strip().rstrip("/").removesuffix(".git")
    customer_repo_name = task_vals["key"]
    module_repo_name = module_repository.split("/")[-1]
    module_organisation = module_repository.split("/")[-2]
    module_full_repo_name = f"{module_organisation}/{module_repo_name}"
    module_repo_url = f"{GITHUB_URL}:{module_full_repo_name}.git"
    odoo_version = task_vals["odoo_version_id"][1]
    customer_dir = os.path.join(addons.PROJECT_DIR, customer_repo_name)

    if not os.path.exists(customer_dir):
        addons.Addons(slug=customer_repo_name, init=True)
        print(f"📂 Created deployment folder: {customer_dir}")

    if module_name == "*":
        feature_branch_name = f"{task_id}-{odoo_version}-{module_repo_name}"
    else:
        feature_branch_name = f"{task_id}-{odoo_version}-{module_name}"
    # Create feature branch in config repo
    config_repo = git_handler.get_repo(
        customer_repo_name, os.path.join(customer_dir, addons.CONFIG_DIR)
    )
    git_handler.create_feature_branch(
        config_repo, odoo_version, feature_branch_name, "Config"
    )

    # Handle addons.yaml update
    addons_yaml_path = os.path.abspath(
        os.path.join(customer_dir, "config", "addons.yaml")
    )
    addons_state = yaml_handler.update_yaml(
        addons_yaml_path, module_full_repo_name, module_name, task_id
    )

    # Handle repos.yaml update
    repos_yaml_path = os.path.abspath(
        os.path.join(customer_dir, "config", "repos.yaml")
    )
    new_entry = {
        "defaults": {"depth": 1},
        "remotes": {module_organisation: module_repo_url},
        "merges": [f"{module_organisation} {odoo_version}"],
    }
    yaml_handler.update_yaml(
        repos_yaml_path, module_full_repo_name, new_entry, task_id, is_addons=False
    )
    git_handler.push(
        config_repo, task_vals, addons_state, [addons_yaml_path, repos_yaml_path]
    )

    # Create feature branch in deployment repo
    deployment_repo = git_handler.get_repo(
        customer_repo_name, os.path.join(customer_dir, addons.ADDONS_DIR)
    )
    deployment_main_branch = git_handler.get_default_branch(deployment_repo)
    git_handler.create_feature_branch(
        deployment_repo, deployment_main_branch, feature_branch_name, "Deployment"
    )

    if generate:
        generate_addons_folder(task_vals, repo_name, git_handler)


@cli.command("freeze")
@click.option(
    "-p", "--project", type=str, help="Define a Project in a multi_project environment"
)
@click.option(
    "-d", "--repo-dir", default=None, help="Only update a specific repo directory"
)
@click.option("-f", "--force", is_flag=True, help="Force update even if auto: 0 is set")
def freeze(project=False, repo_dir=False, force=False):
    """Freeze all repos in SRC_DIR by updating merges entry in repos.yaml with current commit hash, or only the specified repo with -d. Use -f to force update even if auto: 0 is set."""
    customer_instance = addons.Addons(slug=project)
    odoo_version = customer_instance.odoo_version
    src_dir = customer_instance.src_dir
    repos_yaml_path = customer_instance.repos_yaml
    yaml_handler = YAMLHandler()
    repos_data = yaml_handler.load(repos_yaml_path)
    updated = False
    for repo_key, repo_info in repos_data.items():
        # If -d is set, skip all except the specified repo
        repo_key = repo_key.lstrip("./")
        if repo_dir and repo_key != repo_dir:
            continue
        defaults = repo_info.get("defaults", {})
        if not force and defaults.get("auto", 1) == 0:
            print(f"⏭️ Skipping freeze for {repo_key} (auto: 0)")
            continue
        repo_path = os.path.join(src_dir, repo_key)
        if not os.path.isdir(repo_path):
            print(f"❌ Repo dir not found: {repo_path}")
            continue
        remotes = repo_info.get("remotes", {})
        if not remotes:
            print(f"❌ No remotes defined for {repo_key}")
            continue
        first_remote_alias = next(iter(remotes.keys()))
        default_branch = defaults.get("branch", odoo_version)
        try:
            repo = git.Repo(repo_path)
            remote_url = remotes[first_remote_alias]
            # Try to get the commit hash of the default branch from the remote
            refs = repo.git.ls_remote(
                remote_url, f"refs/heads/{default_branch}"
            ).splitlines()
            if not refs:
                print(
                    f"❌ Could not find branch {default_branch} on remote {remote_url}"
                )
                continue
            commit_hash = refs[0].split()[0]
            merges = repo_info.get("merges", [])
            # Ensure merges is always a list (preserve ruamel.yaml type if possible)
            if not isinstance(merges, list):
                merges = list(merges)
            old_hash = None
            if merges:
                parts = merges[0].split()
                if len(parts) > 1:
                    old_hash = parts[1]
                if old_hash == commit_hash:
                    continue
                merges[0] = f"{first_remote_alias} {commit_hash}"
            else:
                merges = CommentedSeq([f"{first_remote_alias} {commit_hash}"])
            repo_info["merges"] = merges
            print(f"🔒 {repo_key}: {first_remote_alias} {commit_hash}")
            updated = True
        except Exception as e:
            print(f"❌ Error freezing {repo_key}: {e}")
            sys.exit(1)
    if updated:
        yaml_handler.save(repos_yaml_path, repos_data)
        print("✅ repos.yaml updated with frozen commit hashes.")


def generate_addons_folder(project=False, repo_name=False, git_handler=False):
    """Generate addon folders by copying from the source."""

    customer_instance = addons.Addons(slug=project)

    # Remove old addon folders
    for addon in iglob(os.path.join(customer_instance.addons_dir, "*")):
        if os.path.isdir(addon):
            # TODO: Keep customer folder but recreate the content if available.
            shutil.rmtree(addon)

    addons_yaml_path = os.path.abspath(customer_instance.config_yaml)
    repos_yaml_path = os.path.abspath(customer_instance.repos_yaml)

    config_repo = git_handler.get_repo(project, customer_instance.config_dir)
    config_repo.git.add([addons_yaml_path, repos_yaml_path])
    try:
        command_args = [
            "gitaggregate",
            "-c",
            repos_yaml_path,
            "-j",
            "64",
            "--log-level",
            "ERROR",
        ]
        if repo_name:
            command_args += ["-d", repo_name]
        check_call(
            command_args,
            cwd=customer_instance.src_dir,
            # Enable logging until stable enough
            # stderr=subprocess.DEVNULL,
            # stdout=subprocess.DEVNULL,
        )
        print(f"✅ Successfully ran gitaggregate for {project}")
    except subprocess.CalledProcessError as e:
        print(f"❌ Error occurred while running gitaggregate: {e}")
        sys.exit(1)

    addons_list = []
    # Copy addons to target directory
    for addon, repo in customer_instance.addons_list():
        src = os.path.join(customer_instance.src_dir, repo, addon)
        dst = os.path.join(customer_instance.addons_dir, repo, addon)
        addons_list.append(dst)
        shutil.copytree(src, dst)

    print(f"✅ Addon folders generated for {project}")

    requirements = set(customer_instance.get_external_requirements(addons_list))
    requirements_path = os.path.join(customer_instance.addons_dir, "requirements.txt")
    auto_marker = "# auto-generated from modules"

    manual_lines = []

    # Read existing file line-by-line
    if os.path.exists(requirements_path):
        with open(requirements_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip() == auto_marker:
                    break  # Stop at marker
                dep = line.strip()
                if dep and not dep.startswith("#") and dep in requirements:
                    continue  # Skip duplicate of auto-generated
                manual_lines.append(line)

    # Ensure there's a newline before the marker if needed
    if manual_lines and not manual_lines[-1].endswith("\n"):
        manual_lines[-1] += "\n"
    manual_lines.append(auto_marker + "\n")
    # Compute diff for requirements.txt
    old_requirements = set()
    if os.path.exists(requirements_path):
        with open(requirements_path, "r", encoding="utf-8") as f:
            in_auto = False
            for line in f:
                if line.strip() == auto_marker:
                    in_auto = True
                    continue
                if in_auto:
                    dep = line.strip()
                    if dep:
                        old_requirements.add(dep)
    added = requirements - old_requirements
    removed = old_requirements - requirements
    replaced = set()

    # In requirements.txt context, replaced lines are those both removed and added with similar names (not exact match)
    # For simplicity, count as replaced if a requirement with same package name but different version is present
    def pkg_name(req):
        return (
            req.split("==")[0]
            if "==" in req
            else req.split(">=")[0]
            if ">=" in req
            else req
        )

    old_pkgs = {pkg_name(r): r for r in old_requirements}
    new_pkgs = {pkg_name(r): r for r in requirements}
    for name in old_pkgs:
        if name in new_pkgs and old_pkgs[name] != new_pkgs[name]:
            replaced.add((old_pkgs[name], new_pkgs[name]))
            removed.discard(old_pkgs[name])
            added.discard(new_pkgs[name])
    # Write final file
    with open(requirements_path, "w", encoding="utf-8") as f:
        f.writelines(manual_lines)
        for dep in sorted(requirements):
            f.write(dep + "\n")

    print(
        f"➕ {len(added)} lines added, ➖ {len(removed)} lines removed, 🔁 {len(replaced)} lines replaced in requirements.txt"
    )
    # Generate commit message for changed modules
    repo = git.Repo(customer_instance.addons_dir)
    diff_index = repo.index.diff(None)  # staged and unstaged changes
    changed_files = set()
    for diff in diff_index.iter_change_type("A"):
        changed_files.add((diff.a_path, "ADD"))
    for diff in diff_index.iter_change_type("M"):
        changed_files.add((diff.a_path, "UPDATE"))
    for diff in diff_index.iter_change_type("D"):
        changed_files.add((diff.a_path, "REM"))

    # Only include modules from addons_list
    module_paths = set()
    for path in addons_list:
        rel_path = os.path.relpath(path, customer_instance.addons_dir)
        module_name = os.path.basename(path)
        module_paths.add((module_name, rel_path))

    commit_lines = ["Automated module update"]
    for module_name, rel_path in module_paths:
        for file_path, change_type in changed_files:
            if file_path.startswith(rel_path):
                commit_lines.append(f"[{change_type}] {module_name} {rel_path}")
                print(f"📁 {change_type} {module_name} in {rel_path}")
                break

    commit_message = "\n".join(commit_lines)
    repo.git.add(all=True)
    if repo.is_dirty(untracked_files=True):
        repo.index.commit(commit_message)
        print("✅ Changes committed to addons repo.")
    else:
        print("ℹ️ No changes to commit in addons repo.")


@cli.command("clean")
@click.argument("task_id", type=int)
def clean(task_id):
    """Discard all changes and untracked files in both config and addons repos for a specific task."""
    odoo_client = OdooClient(ODOO_URL, ODOO_DB, ODOO_USER, ODOO_TOKEN)
    task_vals = odoo_client.get_task(task_id)

    customer_repo_name = task_vals["key"]
    customer_dir = os.path.join(addons.PROJECT_DIR, customer_repo_name)
    repo_paths = {
        "Config": os.path.join(customer_dir, addons.CONFIG_DIR),
        "Addons": os.path.join(customer_dir, addons.ADDONS_DIR),
    }

    # Clean config and addons repos
    for name, path in repo_paths.items():
        try:
            repo = git.Repo(path)
            print(f"🧹 Cleaning {name} repo at {path}...")
            repo.git.reset("--hard")
            repo.git.clean("-fd")
            print(f"✅ {name} directory cleaned.")
        except git.exc.InvalidGitRepositoryError:
            print(f"❌ {path} is not a valid Git repository.")
            sys.exit(1)
        except Exception as e:
            print(f"❌ Error while cleaning the {name} repo: {e}")
            sys.exit(1)

    # Clean all repos in SRC_DIR from repos.yaml
    # TODO: get yaml from Addons instance
    repos_yaml_path = os.path.join(repo_paths["Config"], "repos.yaml")
    if os.path.exists(repos_yaml_path):
        yaml = YAML()
        with open(repos_yaml_path, "r") as f:
            repos_data = yaml.load(f) or {}
        for repo_dir in repos_data.keys():
            # Remove leading './' if present
            repo_path = os.path.join(
                addons.SRC_DIR, repo_dir[2:] if repo_dir.startswith("./") else repo_dir
            )
            if os.path.isdir(repo_path):
                try:
                    repo = git.Repo(repo_path)
                    repo.git.reset("--hard")
                    repo.git.clean("-fd")
                    print(f"✅ SRC_DIR repo cleaned: {repo_path}")
                except git.exc.InvalidGitRepositoryError:
                    print(f"❌ {repo_path} is not a valid Git repository.")
                    sys.exit(1)
                except Exception as e:
                    print(f"❌ Error while cleaning SRC_DIR repo {repo_path}: {e}")
                    sys.exit(1)


@cli.command("init")
@click.argument("customer")
def init_customer_folders(customer):
    """Initialize customer folder structure."""
    addons.Addons(slug=customer, init=True)
    print(f"📂 Customer folders initialized for {customer}")


@cli.command("generate")
@click.option("-p", "--project", type=str, default=None)
@click.option("-d", "--repo-name", default=None, help="Repository to limit generation")
def generate_addons_folder_click(project, repo_name):
    git_handler = GitHandler(GITHUB_ORG)
    generate_addons_folder(project, repo_name, git_handler)


cli.add_command(create)
cli.add_command(clean)
cli.add_command(init_customer_folders)
cli.add_command(generate_addons_folder_click)

if __name__ == "__main__":
    cli()
