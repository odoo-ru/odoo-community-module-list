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

# Result schema:
# {'user':
#     {'repo':
#         {'version':
#             {'module': str,
#              'name': str,
#              'summary': str,
#             }
#         }
#     }
# }

class ModuleCollector:
    def __init__(self, github_access_token):
        self.github = Github(github_access_token, per_page=100)
        self.data: Dict[(str, str, int, str), dict] = {}

    def load(self, file_path):
        with open(file_path, 'rb') as file:
            self.data = pickle.load(file)

    def save(self, file_path):
        with open(file_path, 'wb') as file:
            logger.info('Dump data to %s', file_path)
            pickle.dump(self.data, file)

    def last_updated_key(self):
        timestamp = 0
        result = None
        if not self.data:
            logger.info('Use last updated init key')
            return '', '', 1, ''
        for key, value in self.data.items():
            # if timestamp > value['timestamp']:
            if timestamp < value['timestamp']:
                # search minimum
                timestamp = value['timestamp']
                result = key
        logger.info('Found last updated key: %s for timestamp: %s', result, timestamp)
        return result

    @staticmethod
    def ordered_org_logins(org_logins, last_updated_org_login):
        """
        Sort and rotate org_logins to make last_updated_ord_login on first position
        >>> mc = ModuleCollector()
        >>> mc.ordered_org_logins(['c', 'b', 'a', 'd'], 'b')
        ['b', 'c', 'd', 'a']
        """
        org_logins = sorted(org_logins)
        if last_updated_org_login not in org_logins:
            return org_logins
        last_updated_org_index = org_logins.index(last_updated_org_login)
        return org_logins[last_updated_org_index:] + org_logins[:last_updated_org_index]

    def collect(self, org_logins, odoo_versions):
        last_updated_key = self.last_updated_key()
        last_updated_org_login, last_updated_repo, last_updated_version, last_updated_module = last_updated_key
        if last_updated_org_login not in org_logins:
            last_updated_org_login, last_updated_repo, last_updated_version, last_updated_module = (
                None, None, 0, None
            )
        logger.info('Use last updated key: %s', (last_updated_org_login, last_updated_repo, last_updated_version, last_updated_module))

        for org_login in self.ordered_org_logins(org_logins, last_updated_org_login):
            # if org_login < last_updated_org_login:
            #     continue
            logger.info('Get %s user repos', org_login)
            org = self.github.get_organization(org_login)

            repos = org.get_repos(type='sources', sort='full_name')
            if last_updated_repo:
                repos = itertools.dropwhile(lambda x: x.name < last_updated_repo, repos)

            for repo in repos:
                if repo.name in {'.github'}:
                    continue

                logger.info(f'Check: {repo.full_name}')

                # for version in filter(lambda x: x >= last_updated_version, odoo_versions):
                for version in odoo_versions:
                    if last_updated_module and version < last_updated_version:
                        continue

                    version_branch = f'{version}.0'
                    try:
                        contents = repo.get_contents('', ref=version_branch)
                    except GithubException as error:
                        # TODO Remove all version
                        logging.info(f'No branch: {repo.full_name}/{version_branch}')
                        continue

                    for module in sorted(contents, key=lambda x: x.name):
                        if module.type != 'dir':
                            continue

                        if module.name in {'.github', '.tx', 'setup'}:
                            continue

                        if last_updated_module and module.name < last_updated_module:
                            continue

                        manifest_path = os.path.join(module.path, '__manifest__.py')
                        try:
                            manifest_file = repo.get_contents(manifest_path, ref=version_branch)
                        except UnknownObjectException:
                            logging.info(f'Skip {repo.full_name}/{version_branch}. Found: {module.name}')
                            break

                        manifest = ast.literal_eval(manifest_file.decoded_content.decode('utf8'))
                        module_key = org_login, repo.name, version, module.name
                        logger.info('Updated: %s', module_key)
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
                    last_updated_module = None
                last_updated_version = 0
            last_updated_repo = None

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
