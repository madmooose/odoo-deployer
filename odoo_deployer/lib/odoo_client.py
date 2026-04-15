import xmlrpc.client
import sys

try:
    from .. import ODOO_TYPE_DEPLOYMENT, ODOO_STAGE_ACKNOWLEDGE
except ImportError:
    # fallback for direct script usage or testing
    ODOO_TYPE_DEPLOYMENT = 0
    ODOO_STAGE_ACKNOWLEDGE = 0


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
        required_task_fields = [
            "project_id",
            "type_id",
            "stage_id",
            "key",
            "ife_repository",
            "ife_repository",
            "module_name",
            "odoo_version_id",
            "hosting",
            "customer_repository",
        ]

        required_project_fields = [
            "ife_repository",
        ]

        try:
            task = self.models.execute_kw(
                self.db,
                self.uid,
                self.token,
                "project.task",
                "read",
                [[task_id], required_task_fields],
            )
            if not task:
                raise ValueError("Task not found")

            task_data = task[0]
            project_id = int(task_data["project_id"][0])  # Use the integer ID

            project = self.models.execute_kw(
                self.db,
                self.uid,
                self.token,
                "project.project",
                "read",
                [[project_id], required_project_fields],
            )
            if not project:
                raise ValueError("Project not found")

            project_data = project[0]
            errors = []

            missing_task_fields = [
                field for field in required_task_fields if not task_data.get(field)
            ]
            if missing_task_fields:
                errors.append(
                    f"Missing required fields: {', '.join(missing_task_fields)}"
                )

            missing_project_fields = [
                field
                for field in required_project_fields
                if not project_data.get(field)
            ]
            if missing_project_fields:
                errors.append(
                    f"Missing required fields: {', '.join(missing_project_fields)}"
                )

            if (
                task_data.get("type_id")
                and task_data.get("type_id")[0] != ODOO_TYPE_DEPLOYMENT
            ):
                errors.append(
                    f"Invalid type_id: {task_data.get('type_id')[1]}. Expected Deployment."
                )

            if (
                task_data.get("stage_id")
                and task_data.get("stage_id")[0] != ODOO_STAGE_ACKNOWLEDGE
            ):
                errors.append(
                    f"Invalid stage_id: {task_data.get('stage_id')[1]}. Expected Acknowledge."
                )

            if task_data.get("hosting") != "odoo_sh":
                errors.append(
                    f"Invalid hosting: {task_data.get('hosting')}. Expected 'odoo_sh'."
                )

            if project_data.get("ife_repository"):
                task_data["project_ife_repository"] = project_data.get("ife_repository")
            else:
                errors.append("Project ife_repository is not set.")

            if errors:
                raise ValueError("\n".join(errors))

            return task_data

        except Exception as e:
            print(f"❌ Error fetching task information: \n{e}")
            sys.exit(1)
