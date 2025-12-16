import os
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedSeq, CommentedMap


class YAMLHandler:
    """Handles YAML file operations for addons and repos."""

    def __init__(self):
        self.yaml = YAML()
        self.yaml.preserve_quotes = True
        self.yaml.width = 1000
        self.yaml.indent(mapping=2, sequence=4, offset=2)

    def load(self, file_path):
        """Load YAML data from a file."""
        if os.path.exists(file_path):
            with open(file_path, "r") as f:
                return self.yaml.load(f) or {}
        return {}

    def save(self, file_path, data):
        """Save YAML data to a file."""
        with open(file_path, "w") as f:
            self.yaml.dump(data, f)

    def update_yaml(self, file_path, repo_name, new_entry, task_id, is_addons=True):
        """Updates addons.yaml or repos.yaml with the new module or repository."""
        existing_data = self.load(file_path)
        if is_addons:
            return self.update_addons_yaml(
                file_path, existing_data, repo_name, new_entry, task_id
            )
        else:
            return self.update_repos_yaml(
                file_path, existing_data, repo_name, new_entry, task_id
            )

    def update_addons_yaml(
        self, file_path, existing_data, repo_name, new_entry, task_id
    ):
        """Update addons.yaml with a new module or entry."""
        state = "unknown"
        if repo_name in existing_data:
            modules = existing_data[repo_name]
        else:
            modules = []

        if not isinstance(modules, CommentedSeq):
            modules = CommentedSeq(modules)
            # Add a blank line before the new repo key
            if existing_data:
                existing_data.yaml_set_comment_before_after_key(repo_name, before="\n")
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

        self.save(file_path, existing_data)
        return state

    def update_repos_yaml(
        self, file_path, existing_data, repo_name, new_entry, task_id
    ):
        """Update repos.yaml with a new repository if it doesn't exist already."""
        changed = False

        if not isinstance(existing_data, CommentedMap):
            existing_data = CommentedMap(existing_data)

        if repo_name[0] != ".":
            repo_name = f"./{repo_name}"

        if repo_name not in existing_data:
            # Add a blank line before the new repo key
            if existing_data:
                existing_data.yaml_set_comment_before_after_key(repo_name, before="\n")
            existing_data[repo_name] = new_entry
            print(f"📄 Added '{repo_name}' to repos.yaml at {file_path}")
            new_comment = f"Added from task {task_id}"
            existing_data.yaml_add_eol_comment(new_comment, repo_name)
            changed = True

        if changed:
            self.save(file_path, existing_data)

        return changed
