import itertools
import os
import ast
import logging
import pickle
import time
from typing import Dict

from github import Github, GithubException, UnknownObjectException, RateLimitExceededException

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger()


class ModuleCollector:
    NULL_MODULE_KEY = None, None, 0, None

    def __init__(self, github_access_token):
        self.github = Github(github_access_token, per_page=100)
        self.data: Dict[(str, str, int, str), dict] = {}
        (
            self.last_updated_org_login,
            self.last_updated_repo,
            self.last_updated_version,
            self.last_updated_module,
        ) = self.NULL_MODULE_KEY

    def load(self, file_path):
        with open(file_path, 'rb') as file:
            self.data = pickle.load(file)

    def save(self, file_path):
        with open(file_path, 'wb') as file:
            logger.info('Dump data to %s', file_path)
            pickle.dump(self.data, file)

    def last_updated_key(self, org_logins):
        last_updated_module_key = self.NULL_MODULE_KEY
        timestamp = 0
        for module_key, module_values in self.data.items():
            # search the latest timestamp
            if timestamp < module_values['timestamp']:
                timestamp = module_values['timestamp']
                last_updated_module_key = module_key

        if last_updated_module_key[0] not in org_logins:
            last_updated_module_key = self.NULL_MODULE_KEY

        (
            self.last_updated_module,
            self.last_updated_repo,
            self.last_updated_version,
            self.last_updated_module,
        ) = last_updated_module_key
        logger.info('Use last updated module key: %s', last_updated_module_key)

    def ordered_org_logins(self, org_logins):
        """
        Sort and rotate org_logins to make last_updated_ord_login on first position
        >>> mc = ModuleCollector()
        >>> mc.ordered_org_logins(['c', 'b', 'a', 'd'], 'b')
        ['b', 'c', 'd', 'a']
        """
        org_logins = sorted(org_logins)
        if self.last_updated_org_login not in org_logins:
            return org_logins
        last_updated_org_index = org_logins.index(self.last_updated_org_login)
        return org_logins[last_updated_org_index:] + org_logins[:last_updated_org_index]

    def collect(self, org_logins, odoo_versions):
        self.last_updated_key(org_logins)

        for org_login in self.ordered_org_logins(org_logins):
            self.scan_organization(org_login, odoo_versions)
            self.last_updated_repo = None

    def scan_organization(self, org_login, odoo_versions):
        logger.info('%s: Scanning', org_login)

        org = self.github.get_organization(org_login)
        repos = org.get_repos(type='sources', sort='full_name')
        if self.last_updated_repo:
            repos = itertools.dropwhile(lambda x: x.name < self.last_updated_repo, repos)

        for repo in repos:
            if repo.name in {'.github'}:
                continue

            self.scan_repo(org_login, repo, odoo_versions)
            self.last_updated_version = 0

    def scan_repo(self, org_login, repo, odoo_versions):
        logger.info('%s %s: Scanning', org_login, repo.name)

        for version in odoo_versions:
            if self.last_updated_module and version < self.last_updated_version:
                continue
            self.scan_repo_branch(org_login, repo, version)
            self.last_updated_module = None

    def scan_repo_branch(self, org_login, repo, version):
        version_branch = f'{version}.0'
        try:
            contents = repo.get_contents('', ref=version_branch)
        except GithubException as error:
            logging.info('%s %s: No branch %s', org_login, repo.name, version_branch)
            return

        logger.info('%s %s %s: Scanning', org_login, repo.name, version)

        for module in sorted(contents, key=lambda x: x.name):
            if module.type != 'dir':
                continue

            if module.name in {'.github', '.tx', 'setup'}:
                continue

            if self.last_updated_module and module.name < self.last_updated_module:
                continue

            self.scan_module(org_login, repo, version, module)

    def scan_module(self, org_login, repo, version, module):
        version_branch = f'{version}.0'
        manifest_path = os.path.join(module.path, '__manifest__.py')
        module_key = org_login, repo.name, version, module.name
        try:
            manifest_file = repo.get_contents(manifest_path, ref=version_branch)
        except UnknownObjectException:
            logging.info(f'%s %s %s %s: No manifest file', *module_key)
            return

        manifest = ast.literal_eval(manifest_file.decoded_content.decode('utf8'))
        self.data[module_key] = {
            'user': org_login,
            'module': module.name,
            'odoo_version': version,
            'timestamp': time.time(),

            'repo': repo.name,
            'stars': repo.stargazers_count,

            'last_modified': module.last_modified,
            'html_url': module.html_url,
            'name': manifest['name'],
            'summary': manifest.get('summary', '').strip(),
        }
        logger.info('%s %s %s %s: Updated', *module_key)

    def safe_collect(self, org_logins, odoo_versions):
        try:
            self.collect(org_logins, odoo_versions)
        except (KeyboardInterrupt, RateLimitExceededException):
            pass


def format_markdown(repos):
    list_items = []
    for repo in sorted(repos, key=lambda r: r.name):
        list_item = f'* [{repo.name}]({repo.svn_url})'
        if repo.description:
            list_item += f' - {repo.description}'

        list_items.append(list_item)

    return '\n'.join(list_items)
