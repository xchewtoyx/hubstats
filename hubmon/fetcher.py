from argparse import ArgumentTypeError
from urllib.request import urlopen, urljoin

from bs4 import BeautifulSoup

from cement.core import controller, foundation, handler

BASE_URL = 'http://192.168.100.1/'
STATUS_PAGES = [
    'info',
    'status',
    'downstream',
    'upstream',
    'usburst',
    'configuration',
]

def table_validator(table):
    if table in STATUS_PAGES:
        return table
    else:
        raise ArgumentTypeError("Argument should be one of: %s" % (
            ' '.join(STATUS_PAGES)))

class BaseController(controller.CementBaseController):
    class Meta:
        label = 'base'

    def fetch_page(self, page):
        page_name = 'VmRouterStatus_%s.asp' % (page)
        url = urljoin(BASE_URL, page_name)
        with urlopen(url) as page_data:
            soup = BeautifulSoup(page_data)
        return soup

    def process_table(self, table):
        caption = table.caption.text
        data = []
        for row in table.findAll('tr'):
            data.append([])
            row_data = data[-1]
            for cell in row.children:
                if hasattr(cell, 'text'):
                    row_data.append(cell.text)
        return caption, data

    @controller.expose(aliases=['help'], aliases_only=True)
    def default(self):
        self.app.args.print_help()


class PrintStats(BaseController):
    class Meta:
        label = 'stats'
        stacked_on = 'base'
        stacked_type = 'nested'
        description = 'Print all status metrics'

    @controller.expose(hide=True)
    def default(self):
        for page in STATUS_PAGES:
            soup = self.fetch_page(page)
            caption, data = self.process_table(soup.table)
            for row in data:
                print(row)

class FetchTable(BaseController):
    class Meta:
        label = 'fetch'
        stacked_on = 'base'
        stacked_type = 'nested'
        description = 'Fetch a status table'
        arguments = [
            (['table'], {
                'action': 'store',
                'help': 'Table to fetch',
                'type': table_validator,
            }),
        ]

    @controller.expose(hide=True)
    def default(self):
        page = self.fetch_page(self.app.pargs.table)
        caption, data = self.process_table(page.table)
        self.app.log.info('Retrieved table %r' % caption)
        for row in data:
            print(row)

def load():
    handler.register(PrintStats)
    handler.register(FetchTable)
