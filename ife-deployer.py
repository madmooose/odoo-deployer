import click
import os
import sys
import json
import git
import shutil
import re
import subprocess
from subprocess import check_call
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedSeq, CommentedMap
import xmlrpc.client
from glob import iglob
from dotenv import load_dotenv
from lib import addons

load_dotenv(override=True)
GITHUB_URL = os.getenv("GITHUB_URL")
GITHUB_ORG = os.getenv("GITHUB_ORG")
ODOO_URL = os.getenv("ODOO_URL")
ODOO_DB = os.getenv("ODOO_DB")
ODOO_USER = os.getenv("ODOO_USER")
ODOO_TOKEN = os.getenv("ODOO_TOKEN")
ODOO_STAGE_ACKNOWLEDGE = int(os.getenv("ODOO_STAGE_ACKNOWLEDGE"))
ODOO_TYPE_DEPLOYMENT = int(os.getenv("ODOO_TYPE_DEPLOYMENT"))

class OdooClient:
    """Handles connection and interactions with Odoo through XML-RPC."""

    def __init__(self, url, db, user, token):
        self.url = url
        self.db = db
        self.user = user
        self.token = token
        self.uid = None
        self.models = None
        self.connect()

    def connect(self):
        """Establish connection to Odoo and authenticate the user."""
        try:
            client = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/common")
            client.version()
            self.uid = client.authenticate(self.db, self.user, self.token, {})
            if not self.uid:
                raise ValueError("Authentication failed")
            self.models = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/object")
            print("✅ Successfully connected to Odoo")
        except Exception as e:
            print(f"❌ Error connecting to Odoo: {e}")
            sys.exit(1)

    def get_task(self, task_id):
        """Retrieve task details from Odoo using the task ID."""
        required_fields = [
            'type_id', 'stage_id', 'key', 'ife_repository', 'module_name',
            'odoo_version_id', 'hosting', 'customer_repository'
        ]

        try:
            task = self.models.execute_kw(
                self.db, self.uid, self.token, 'project.task', 'read',
                [[task_id], required_fields]
            )

            if not task:
                raise ValueError("Task not found")

            task_data = task[0]
            errors = []

            missing_fields = [field for field in required_fields if not task_data.get(field)]
            if missing_fields:
                errors.append(f"Missing required fields: {', '.join(missing_fields)}")

            if task_data.get('type_id') and task_data.get('type_id')[0] != ODOO_TYPE_DEPLOYMENT:
                errors.append(f"Invalid type_id: {task_data.get('type_id')[1]}. Expected Deployment.")

            if task_data.get('stage_id') and task_data.get('stage_id')[0] != ODOO_STAGE_ACKNOWLEDGE:
                errors.append(f"Invalid stage_id: {task_data.get('stage_id')[1]}. Expected Acknowledge.")

            if task_data.get('hosting') != 'odoo_sh':
                errors.append(f"Invalid hosting: {task_data.get('hosting')}. Expected 'odoo_sh'.")

            if errors:
                raise ValueError("\n".join(errors))

            return task_data

        except Exception as e:
            print(f"❌ Error fetching task information: \n{e}")
            sys.exit(1)

class GitHandler:
    """Handles Git repository operations such as cloning and fetching updates."""

    def __init__(self, github_org):
        self.github_org = github_org

    def get_repo(self, slug, deployment_folder):
        """Clone the repository if not present, otherwise fetch the latest updates."""
        if not os.path.exists(deployment_folder):
            try:
                repo = git.Repo.clone_from(f"{self.github_org}/{slug}", deployment_folder)
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
            default_branch_names = ['refs/heads/live', 'refs/heads/main', 'refs/heads/master']

            repo.remotes.origin.fetch()
            remote_branches = [line.split()[1] for line in repo.git.ls_remote('--heads', 'origin').splitlines()]

            for branch in default_branch_names:
                if branch in remote_branches:
                    repo.git.checkout(branch)
                    repo.git.pull('origin', branch)
                    return branch.split('/')[2]


            # TODO: Find a proper why to get the default branch from GitHub
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
                print(f"❌ {description} Repository is dirty. Please commit or stash changes.")
                sys.exit(1)
            if branch_name in repo.heads:
                print(f"🔄 {description} branch '{branch_name}' already exists. Deleting it.")
                repo.delete_head(branch_name, force=True)


            new_branch = repo.create_head(branch_name, base_branch)
            new_branch.checkout()
            repo.git.push('origin', '--force', branch_name)
            print(f"✅ Created and pushed new {description} branch: {branch_name} based on {base_branch}")
        except Exception as e:
            print(f"❌ Error creating feature branch: {e}")
            sys.exit(1)
        return new_branch

    def push(self, repo, task_vals, state, files):
        """Push changes to the remote repository."""
        try:
            if files:
                repo.git.add(files)
            else:
                repo.git.add('.')
            if state == "added":
                commit_message = f"[{task_vals['id']}][ADD] {task_vals['module_name']}"
            else:
                commit_message = f"[{task_vals['id']}][UPDATE] {task_vals['module_name']}"
            repo.git.commit('-m', commit_message)
            repo.git.push('origin', repo.active_branch.name)
            print(f"✅ Pushed changes to {repo.active_branch.name} branch")
        except Exception as e:
            print(f"❌ Error pushing changes: {e}")
            sys.exit(1)

class YAMLHandler:
    """Handles YAML file operations for addons and repos."""

    def __init__(self):
        self.yaml = YAML()
        self.yaml.preserve_quotes = True
        self.yaml.width = 1000
        self.yaml.indent(mapping=2, sequence=4, offset=2)

    def update_yaml(self, file_path, repo_name, new_entry, task_id, is_addons=True):
        """Updates addons.yaml or repos.yaml with the new module or repository."""
        if os.path.exists(file_path):
            with open(file_path, 'r') as file:
                existing_data = self.yaml.load(file) or {}
        else:
            existing_data = {}

        if is_addons:
            return self.update_addons_yaml(file_path, existing_data, repo_name, new_entry, task_id)
        else:
            return self.update_repos_yaml(file_path, existing_data, repo_name, new_entry, task_id)

    def update_addons_yaml(self, file_path, existing_data, repo_name, new_entry, task_id):
        """Update addons.yaml with a new module or entry."""
        state = "unknown"
        if repo_name in existing_data:
            modules = existing_data[repo_name]
        else:
            modules = []

        if not isinstance(modules, CommentedSeq):
            modules = CommentedSeq(modules)
            existing_data[repo_name] = modules

        if new_entry not in modules:
            modules.append(new_entry)
            modules.yaml_add_eol_comment(f"Added from task {task_id}", len(modules) - 1)
            state = "added"
            print(f"📄 Added '{new_entry}' to addons.yaml at {file_path}")
        else:
            index = modules.index(new_entry)
            modules.yaml_add_eol_comment(f"Updated with task {task_id}", index)
            state = "updated"
            print(f"📄 Updated comment for '{new_entry}' in addons.yaml at {file_path}")

        with open(file_path, 'w') as file:
            self.yaml.dump(existing_data, file)

        return state

    def update_repos_yaml(self, file_path, existing_data, repo_name, new_entry, task_id):
        """Update repos.yaml with a new repository."""
        if not isinstance(existing_data, CommentedMap):
            existing_data = CommentedMap(existing_data)

        if not repo_name in existing_data:
            existing_data[repo_name] = new_entry
            print(f"📄 Added '{repo_name}' to repos.yaml at {file_path}")
            new_comment = f"Added from task {task_id}"
            existing_data.yaml_add_eol_comment(new_comment, repo_name)

        with open(file_path, 'w') as file:
            self.yaml.dump(existing_data, file)

@click.group()
def cli():
    """CLI for managing Odoo module deployment."""
    pass

# python ife-deployer.py create 123 --generate -d ife_project
@cli.command()
@click.argument("task_id", type=int)
@click.option("--generate", is_flag=True, help="Also run generate step after create")
@click.option("-d", "--repo-name", default=None, help="Repository to limit generation")
def create(task_id, generate, repo_name):
    """Deploy a module by fetching from GitHub and verifying with Odoo."""
    odoo_client = OdooClient(ODOO_URL, ODOO_DB, ODOO_USER, ODOO_TOKEN)
    git_handler = GitHandler(GITHUB_ORG)
    yaml_handler = YAMLHandler()

    task_vals = odoo_client.get_task(task_id)

    module_repository = task_vals['ife_repository']
    customer_repo_name = task_vals['key']
    module_repo_name = module_repository.split('/')[-1]
    module_organisation = module_repository.split('/')[-2]
    module_full_repo_name = f"{module_organisation}/{module_repo_name}"
    module_repo_url = f"{GITHUB_URL}:{module_full_repo_name}.git"
    odoo_version = task_vals['odoo_version_id'][1]
    customer_dir = os.path.join(addons.PROJECT_DIR, customer_repo_name)
    if module_organisation == "ifegmbh":
        if module_repo_name == "3rd-party":
            module_full_repo_name = "3rd-party"
        else:
            module_full_repo_name = f"ife/{module_repo_name}"

    if not os.path.exists(customer_dir):
        addons.Addons(slug=customer_repo_name, init=True)
        print(f"📂 Created deployment folder: {customer_dir}")

    feature_branch_name = f"{task_vals['id']}-{odoo_version}-{task_vals['module_name']}"
    # Create feature branch in config repo
    config_repo = git_handler.get_repo(customer_repo_name, os.path.join(customer_dir, addons.CONFIG_DIR))
    new_config_branch = git_handler.create_feature_branch(
        config_repo, odoo_version, feature_branch_name, "Config"
    )

    # Handle addons.yaml update
    addons_yaml_path = os.path.abspath(os.path.join(customer_dir, "config", "addons.yaml"))
    addons_state = yaml_handler.update_yaml(addons_yaml_path, module_full_repo_name, task_vals['module_name'], task_vals['id'])

    # Handle repos.yaml update
    repos_yaml_path = os.path.abspath(os.path.join(customer_dir, "config", "repos.yaml"))
    new_entry = {
        "defaults": {"depth": 1},
        "remotes": {module_organisation: module_repo_url},
        "merges": [f"{module_organisation} {odoo_version}"]
    }
    yaml_handler.update_yaml(repos_yaml_path, module_full_repo_name, new_entry, task_vals['id'], is_addons=False)
    git_handler.push(config_repo, task_vals, addons_state, [addons_yaml_path, repos_yaml_path])

    # Create feature branch in deployment repo
    deployment_repo = git_handler.get_repo(customer_repo_name, os.path.join(customer_dir, addons.ADDONS_DIR))
    deployment_main_branch = git_handler.get_default_branch(deployment_repo)
    new_deployment_branch = git_handler.create_feature_branch(
        deployment_repo, deployment_main_branch, feature_branch_name, "Deployment"
    )

    if generate:
        generate_addons_folder(task_vals, repo_name, git_handler)

def generate_addons_folder(task_vals, repo_name, git_handler):
    """Generate addon folders by copying from the source."""
    odoo_version = task_vals['odoo_version_id'][1]
    customer_slug = task_vals['key']
    customer_instance = addons.Addons(slug=customer_slug)

    # Remove old addon folders
    for addon in iglob(os.path.join(customer_instance.addons_dir, "*")):
        if os.path.isdir(addon):
            shutil.rmtree(addon)

    # Copy addons to target directory
    for addon, repo in customer_instance.addons_list(strict=True, odoo_version=odoo_version):
        src = os.path.join(customer_instance.src_dir, repo, addon)
        dst = os.path.join(customer_instance.addons_dir, repo, addon)
        shutil.copytree(src, dst)
        print(f"📁 Copied {src} to {dst}")

    print(f"✅ Addon folders generated for {customer_slug}")

    customer_dir = os.path.join(addons.PROJECT_DIR, customer_slug)
    addons_yaml_path = os.path.abspath(os.path.join(customer_dir, "config", "addons.yaml"))
    repos_yaml_path = os.path.abspath(os.path.join(customer_dir, "config", "repos.yaml"))

    config_repo = git_handler.get_repo(customer_slug, os.path.join(customer_dir, addons.CONFIG_DIR))
    config_repo.git.add([addons_yaml_path, repos_yaml_path])
    try:
        command_args = ["gitaggregate", "-c", repos_yaml_path, "aggregate"]
        if repo_name:
            command_args = ["gitaggregate", "-c", repos_yaml_path, "aggregate", "-d", repo_name]
        check_call(
            command_args,
            cwd=addons.SRC_DIR,
            stderr=sys.stderr,
            stdout=sys.stdout
        )
        print(f"✅ Successfully ran gitaggregate for {customer_slug}")
    except subprocess.CalledProcessError as e:
        print(f"❌ Error occurred while running gitaggregate: {e}")

@cli.command("init")
@click.argument('customer')
def init_customer_folders(customer):
    """Initialize customer folder structure."""
    customer_instance = addons.Addons(slug=customer, init=True)
    print(f"📂 Customer folders initialized for {customer}")

@cli.command("generate")
@click.argument('task_id', type=int, required=True)
@click.argument('repo_name')
def generate_addons_folder_click(task_id, repo_name=False):
    git_handler = GitHandler(GITHUB_ORG)
    odoo_client = OdooClient(ODOO_URL, ODOO_DB, ODOO_USER, ODOO_TOKEN)
    task_vals = odoo_client.get_task(task_id)
    generate_addons_folder(task_vals, repo_name, git_handler)

cli.add_command(create)
cli.add_command(init_customer_folders)
cli.add_command(generate_addons_folder_click)

if __name__ == '__main__':
    cli()
