import click
from dotenv import load_dotenv
import git
import json
import os
import re
import sys
import xmlrpc.client

# Load environment variables from .env file
load_dotenv()
REPO_DIR = "./repos"
GITHUB_ORG = os.getenv("GITHUB_ORG")
ODOO_URL = os.getenv("ODOO_URL")
ODOO_DB = os.getenv("ODOO_DB")
ODOO_USER = os.getenv("ODOO_USER")
ODOO_TOKEN = os.getenv("ODOO_TOKEN")
DEPLOYMENT_TYPE = 14

def get_odoo_connection(ODOO_URL, ODOO_DB, ODOO_USER, ODOO_TOKEN):
    # TODO: Fetch db name when not provided
    # db_serv_url = 'http://{}/xmlrpc/db'.format(host)
    # sock = xmlrpclib.ServerProxy(db_serv_url)
    # dbs = sock.list()
    # print dbs
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
    return client


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

def get_repo(deployment_folder):
    if not os.path.exists(deployment_folder):
        try:
            repo = git.Repo.clone_from(GITHUB_ORG + '/' + slug, deployment_folder)
        except:
            print("Repository not found or no permission")
            sys.exit(1)
    else:
        try:
            repo = git.Repo(deployment_folder)
            for remote in repo.remotes:
                remote.fetch()
        except Exception as e:
            print(f"Failed to fetch from remote: {e}")
            sys.exit(1)
    return repo

def get_ticket_information(instance, task_id):
    uid = instance.authenticate(ODOO_DB, ODOO_USER, ODOO_TOKEN, {})
    models = xmlrpc.client.ServerProxy('{}/xmlrpc/2/object'.format(ODOO_URL))
    task = models.execute_kw(
        ODOO_DB, uid, ODOO_TOKEN, 'project.task', 'read',
        [[task_id], ['module_name', 'stage_id', 'type_id']]
        )
    if not task:
        raise ValueError("Task not found")
    task = task[0]
    if task.get('type_id')[0] != DEPLOYMENT_TYPE:
        raise ValueError("Not a deployment ticket")
    if not task.get('module_name'):
        raise ValueError("Modulename not provided")
    return json.dumps(task, indent=4)


@click.command()
@click.argument('slug')
@click.argument('ticketnumber', type=int)

def deploy(slug, ticketnumber):
    odoo_instance = get_odoo_connection(ODOO_URL, ODOO_DB, ODOO_USER, ODOO_TOKEN)
    slug, deployment_folder = check_slug(slug)
    repo = get_repo(deployment_folder)
    print(repo.git.status())
    task = get_ticket_information(odoo_instance, ticketnumber)
    print(task)

if __name__ == '__main__':
    deploy()
