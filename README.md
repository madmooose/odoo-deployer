# Usage

## Initialize an Odoo Project

To initialize a new customer folder structure:

```sh
python ife-deployer.py init <customer>
```

## Create and Deploy a Module

To deploy a module by fetching from GitHub and verifying with Odoo:

```sh
python ife-deployer.py create <task_id> [--generate] [-d <repo_name>]
```
- `--generate`: Also run generate step after create
- `-d, --repo-name <repo_name>`: Limit generation to a specific repository

## Generate Addon Folders

To generate addon folders for a given task:

```sh
python ife-deployer.py generate <task_id> [-d <repo_name>]
```
- `-d, --repo-name <repo_name>`: Limit generation to a specific repository

## Clean Repositories

To discard all changes and untracked files in both config and addons repos for a specific task:

```sh
python ife-deployer.py clean <task_id>
```

## Help

To show all available commands and options:

```sh
python ife-deployer.py --help
```
