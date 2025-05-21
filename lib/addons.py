import ast
import logging
import os
from glob import glob
from pprint import pformat

import yaml

PROJECT_DIR = "projects"
CONFIG_DIR = "config"
ADDONS_DIR = "addons"
DATA_DIR = "data"
SRC_DIR = os.path.join(DATA_DIR, "src")
CLEAN = os.environ.get("CLEAN") == "true"
LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})
PRIVATE = "private"
CORE = "odoo/addons"
ENTERPRISE = "enterprise"
MANIFESTS = ("__manifest__.py", "__openerp__.py")

# Customize logging for build
logger = logging.getLogger("doodba")
log_handler = logging.StreamHandler()
log_formatter = logging.Formatter("%(name)s %(levelname)s: %(message)s")
log_handler.setFormatter(log_formatter)
logger.addHandler(log_handler)
_log_level = os.environ.get("LOG_LEVEL", "")
if _log_level.isdigit():
    _log_level = int(_log_level)
elif _log_level in LOG_LEVELS:
    _log_level = getattr(logging, _log_level)
else:
    if _log_level:
        logger.warning("Wrong value in $LOG_LEVEL, falling back to INFO")
    _log_level = logging.INFO
logger.setLevel(_log_level)


class AddonsConfigError(Exception):
    def __init__(self, message, *args):
        super(AddonsConfigError, self).__init__(message, *args)
        self.message = message


class Addons:
    def __init__(self, slug, init=False):
        self.slug = slug
        customer_dir = os.path.join(PROJECT_DIR, self.slug)
        if init:
            if not os.path.isdir(customer_dir):
                os.makedirs(customer_dir)
            else:
                raise FileExistsError("Customer folder already exists")
        else:
            if not os.path.isdir(customer_dir):
                raise FileNotFoundError("Customer folder not found")
        self.addons_dir = os.path.join(customer_dir, ADDONS_DIR)
        if init:
            os.makedirs(self.addons_dir)
        elif not os.path.isdir(self.addons_dir):
            raise FileNotFoundError("Addons folder not found")
        self.config_dir = os.path.join(customer_dir, CONFIG_DIR)
        if init:
            os.makedirs(self.config_dir)
        elif not os.path.isdir(self.config_dir):
            raise FileNotFoundError("Config folder not found")
        self.src_dir = SRC_DIR
        if not os.path.isdir(self.src_dir):
            os.makedirs(self.src_dir)
        self.addons_yaml = os.path.join(self.config_dir, "addons")
        if os.path.isfile("%s.yaml" % self.addons_yaml):
            self.addons_yaml = "%s.yaml" % self.addons_yaml
        elif os.path.isfile("%s.yml" % self.addons_yaml):
            self.addons_yaml = "%s.yml" % self.addons_yaml
        elif init:
            with open("%s.yaml" % self.addons_yaml, "w") as addons_file:
                addons_file.write("# Addons configuration\n")
        else:
            raise FileNotFoundError("addons.yaml not found")
        self.repos_yaml = os.path.join(self.config_dir, "repos")
        if os.path.isfile("%s.yaml" % self.repos_yaml):
            self.repos_yaml = "%s.yaml" % self.repos_yaml
        elif os.path.isfile("%s.yml" % self.repos_yaml):
            self.repos_yaml = "%s.yml" % self.repos_yaml
        elif init:
            with open("%s.yaml" % self.repos_yaml, "w") as repos_file:
                repos_file.write("# Repos configuration")
        else:
            raise FileNotFoundError("repos.yaml not found")

    def extract_manifest_dict(self, path):
        with open(path, encoding="utf-8") as f:
            code = f.read()

        try:
            tree = ast.parse(code, filename=path, mode="exec")
            for node in tree.body:
                if isinstance(node, ast.Expr) and isinstance(node.value, ast.Dict):
                    return ast.literal_eval(node.value)
            raise ValueError("No dictionary found at top level in manifest")
        except Exception as e:
            raise ValueError(f"Cannot extract manifest dictionary: {e}")

    def addons_list(self, filtered=True, strict=False, odoo_version=False):
        """Yield addon name and path from ``ADDONS_YAML``.

        :param bool filtered:
            Use ``False`` to include all addon definitions. Use ``True`` (default)
            to include only those matched by ``ONLY`` clauses, if any.

        :param bool strict:
            Use ``True`` to raise an exception if any declared addon is not found.

        :return Iterator[str, str]:
            A generator that yields ``(addon, repo)`` pairs.
        """

        config = dict()
        missing_glob = set()
        missing_manifest = set()
        all_globs = {}
        try:
            with open(self.addons_yaml) as addons_file:
                for doc in yaml.safe_load_all(addons_file):
                    # Skip sections with ONLY and that don't match
                    only = doc.pop("ONLY", {})
                    if not filtered:
                        doc.setdefault(CORE, ["*"])
                        doc.setdefault(PRIVATE, ["*"])
                    elif any(
                        os.environ.get(key) not in values
                        for key, values in only.items()
                    ):
                        logger.debug("Skipping section with ONLY %s", only)
                        continue
                    # Flatten all sections in a single dict
                    for repo, partial_globs in doc.items():
                        if repo == "ENV":
                            continue
                        logger.debug("Processing %s repo", repo)
                        all_globs.setdefault(repo, set())
                        all_globs[repo].update(partial_globs)
        except IOError:
            logger.debug("Could not find addons configuration yaml.")
        # Add default values for special sections
        # for repo in (CORE, PRIVATE):
        #     all_globs.setdefault(repo, {"*"})
        logger.debug("Merged addons definition before expanding: %r", all_globs)
        # Expand all globs and store config
        for repo, partial_globs in all_globs.items():
            for partial_glob in partial_globs:
                logger.debug("Expanding in repo %s glob %s", repo, partial_glob)
                full_glob = os.path.join(SRC_DIR, repo, partial_glob)
                found = glob(full_glob)
                if not found:
                    # Projects without private addons should never fail
                    if (repo, partial_glob) != (PRIVATE, "*"):
                        missing_glob.add(full_glob)
                    logger.debug("Skipping unexpandable glob '%s'", full_glob)
                    continue
                for addon in found:
                    if not os.path.isdir(addon):
                        continue
                    manifests = (os.path.join(addon, m) for m in MANIFESTS)
                    if not any(os.path.isfile(m) for m in manifests):
                        missing_manifest.add(addon)
                        logger.debug(
                            "Skipping '%s' as it is not a valid Odoo module", addon
                        )
                        continue
                    logger.debug("Registering addon %s", addon)
                    addon = os.path.basename(addon)
                    config.setdefault(addon, set())
                    config[addon].add(repo)
        # Fail now if running in strict mode
        if strict:
            error = []
            if missing_glob:
                error += ["Addons not found:", pformat(missing_glob)]
            if missing_manifest:
                error += ["Addons without manifest:", pformat(missing_manifest)]
            if error:
                raise AddonsConfigError(
                    "\n".join(error), missing_glob, missing_manifest
                )

        logger.debug("Resulting configuration after expanding: %r", config)
        # Check for missing dependencies

        odoo_version = odoo_version.split(".")[0]
        odoo_modules_file = os.path.join(
            os.path.dirname(__file__), f"odoo{odoo_version}_modules.txt"
        )
        standard_modules = set()
        if os.path.isfile(odoo_modules_file):
            with open(odoo_modules_file, "r", encoding="utf-8") as f:
                standard_modules = {line.strip() for line in f if line.strip()}
        else:
            logger.warning(
                "Missing odoo16_modules.txt – skipping standard module check"
            )

        addon_names = set(str(k).strip() for k in config.keys())
        standard_modules = set(str(line).strip() for line in standard_modules)
        all_known = addon_names | standard_modules
        missing_deps = {}

        for addon, repos in config.items():
            addon_path = os.path.join(SRC_DIR, next(iter(repos)), addon)
            manifest_path = None
            for mname in MANIFESTS:
                mpath = os.path.join(addon_path, mname)
                if os.path.isfile(mpath):
                    manifest_path = mpath
                    break
            if not manifest_path:
                continue

            try:
                manifest_data = self.extract_manifest_dict(manifest_path)
                depends = manifest_data.get("depends", [])
                logger.debug(f"Addon: {addon}, Dependencies: {depends}")
                for dep in depends:
                    if dep not in all_known:
                        missing_deps.setdefault(addon, []).append(dep)
            except Exception as e:
                logger.warning(f"Failed to parse manifest {manifest_path}: {e}")

        if missing_deps:
            error_messages = []
            for addon, deps in missing_deps.items():
                error_messages.append(
                    f" - Module '{addon}' has missing dependencies: {', '.join(deps)}"
                )
            print(
                "\n❌ Missing module dependencies:\n" + "\n".join(error_messages) + "\n"
            )
            return

        # Final yield
        for addon, repos in config.items():
            if PRIVATE in repos:
                yield addon, PRIVATE
                continue
            if repos == {CORE}:
                yield addon, CORE
                continue
            repos.discard(CORE)
            if filtered and len(repos) != 1:
                raise AddonsConfigError(
                    f"Addon {addon} defined in multiple repos: {repos}"
                )
            for repo in repos:
                yield addon, repo

    @staticmethod
    def get_external_requirements(addon_paths):
        requirements = set()

        for addon_path in addon_paths:
            manifest_path = None
            for filename in MANIFESTS:
                candidate = os.path.join(addon_path, filename)
                if os.path.isfile(candidate):
                    manifest_path = candidate
                    break
            if not manifest_path:
                raise FileNotFoundError(f"Manifest not found in {addon_path}")

            try:
                with open(manifest_path, encoding="utf-8") as f:
                    manifest_data = ast.literal_eval(f.read())

                ext_deps = manifest_data.get("external_dependencies") or {}
                python_reqs = ext_deps.get("python", {})

                if isinstance(python_reqs, dict):
                    requirements.update(python_reqs.keys())
                elif isinstance(python_reqs, list):
                    requirements.update(python_reqs)
                # else: ignore unexpected formats silently
            except Exception as e:
                print(f"⚠️ Could not parse {manifest_path}: {e}")

        return sorted(requirements)
