# Usage

## Initialize an Odoo Project

To initialize a new customer folder structure:

```sh
python odoo-deployer.py init <customer>
```

## Create and Deploy a Module

Note: For this to work you need to custom repository char field on the tasks model
To deploy a module by fetching from GitHub and verifying with Odoo:

```sh
python odoo-deployer.py create <task_id> [--generate] [-d <repo_name>]
```
- `--generate`: Also run generate step after create
- `-d, --repo-name <repo_name>`: Limit generation to a specific repository

## Freeze Commit Hashes

To get reproducable builds we want to make sure, we always get the same version of a module. This can be archived with referenzing commit hashes instead of branches. In order to update these hashes you can use the freeze command.
You can specify the default branch in the defaults section of the repos.yaml. You can also exclude repos from the freeze command with an auto flag.

```yaml
./oca/partner-contact:
  defaults:
    depth: 1
    branch: 16.0
    auto: 0
  remotes:
    oca: gh:OCA/partner-contact
  merges:
  - oca 7acbeb8d0c21198d69a70ba1b1452a78e2a7aa55
```

```sh
python odoo-deployer.py freeze <task_id> [-d <repo_name>]
```
- `-d, --repo-name <repo_name>`: Limit freezing to a specific repository
- `-f`: Also update auto: 0 entries

## Generate Addon Folders

To generate addon folders for a given task:

```sh
python odoo-deployer.py generate <task_id> [-d <repo_name>]
```
- `-d, --repo-name <repo_name>`: Limit generation to a specific repository

## Clean Repositories

To discard all changes and untracked files in both config and addons repos for a specific task:

```sh
python odoo-deployer.py clean <task_id>
```

## Help

To show all available commands and options:

```sh
python odoo-deployer.py --help
```
