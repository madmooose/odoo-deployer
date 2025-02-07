import click
from dotenv import load_dotenv
import git
import os
import re
import sys

# Load environment variables from .env file
load_dotenv()
REPO_DIR = "./repos"
GITHUB_ORG = os.getenv("GITHUB_ORG")

def check_slug(slug):
    # TODO
    # Check that the slug is a valid GitHub repository name
    if not re.match(r'^[a-zA-Z0-9_-]+$', slug):
        raise ValueError("Slug contains invalid characters")
    base_path = os.path.abspath(REPO_DIR)
    target_path = os.path.abspath(os.path.join(REPO_DIR, slug))
    # Check if the target path is within the base path
    if os.path.commonpath([base_path]) == os.path.commonpath([base_path, target_path]):
        return [slug, target_path]
    else:
        raise ValueError("Path is not valid")

@click.command()
@click.argument('slug')

def deploy(slug):
    slug, deployment_folder = check_slug(slug)
    if not os.path.exists(deployment_folder):
        try:
            repo = git.Repo.clone_from(GITHUB_ORG + '/' + slug, deployment_folder)
        except:
            print("Repository not found or no permission")
            sys.exit(1)
    else:
        repo = git.Repo(deployment_folder)

    print(repo.git.status())

if __name__ == '__main__':
    deploy()
