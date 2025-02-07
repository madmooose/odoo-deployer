import click
from dotenv import load_dotenv
import xmlrpc.client
import git
import os
import re
import sys

# Load environment variables from .env file
load_dotenv()
REPO_DIR = "./repos"
GITHUB_ORG = os.getenv("GITHUB_ORG")
ODOO_URL = os.getenv("ODOO_URL")
ODOO_DB = os.getenv("ODOO_DB")
ODOO_USER = os.getenv("ODOO_USER")
ODOO_TOKEN = os.getenv("ODOO_TOKEN")

def get_odoo_connection(ODOO_URL, ODOO_DB, ODOO_USER, ODOO_TOKEN):
    try:
        client = xmlrpc.client.ServerProxy('{}/xmlrpc/2/common'.format(ODOO_URL))
        client.version()  # Attempt to get the version to check the connection
    except Exception as e:
        print(f"Failed to connect to Odoo: {e}")
        sys.exit(1)
    try:
        uid = client.authenticate(ODOO_DB, ODOO_USER, ODOO_TOKEN, {})
        if not uid:
            raise ValueError("Authentication failed")
    except Exception as e:
        print(f"Database connection failed: {e}")
        sys.exit(1)


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
    odoo_instance = get_odoo_connection(ODOO_URL, ODOO_DB, ODOO_USER, ODOO_TOKEN)
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
