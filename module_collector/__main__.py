import os

from .collect_modules import ModuleCollector
from .settings import GITHUB_ORGANIZATIONS, ODOO_VERSIONS


def update_module_info():
    github_access_token = os.getenv('GITHUB_ACCESS_TOKEN')

    module_collector = ModuleCollector(github_access_token)
    module_collector.load('modules.pickle')
    module_collector.safe_collect(GITHUB_ORGANIZATIONS, ODOO_VERSIONS)
    module_collector.save('modules.pickle')
    print(module_collector.github.rate_limiting)
    print(module_collector.github.rate_limiting_resettime)


if __name__ == '__main__':
    update_module_info()
