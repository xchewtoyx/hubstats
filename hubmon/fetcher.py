from argparse import ArgumentTypeError
import re
from urllib.request import urlopen, urljoin

from bs4 import BeautifulSoup
from cement.core import controller, foundation, handler
import statsd

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
        arguments = [
            (['--statsd'], {
                'help': 'statsd server to send data to (e.g. localhost:8215)',
                'default': None,
                'action': 'store',
            }),
            (['--statsd_prefix'], {
                'help': 'prefix to add to statsd metrics',
                'default': None,
                'action': 'store',
            }),
        ]

    def format_info(self, data):
        return [
            ('modem.info.protocol', data[0][1]),
            ('modem.info.serial', data[1][1]),
            ('modem.info.version.bootcode', data[2][1]),
            ('modem.info.version.software', data[3][1]),
            ('modem.info.version.hardware', data[4][1]),
            ('modem.info.ca_key', data[5][1]),
        ]

    def format_status(self, data):
        return [
            ('modem.status.downstream.frequency', data[1][1]),
            ('modem.status.downstream.status', data[1][2]),
            ('modem.status.upstream.frequency', data[2][1]),
            ('modem.status.upstream.status', data[2][2]),
            ('modem.status.provisioning.status', data[3][1]),
            ('modem.status.provisioning.description', data[3][2]),
        ]

    def metric_table(self, metric_format, name, channels, metrics):
        for index in range(1, len(metrics)):
            metric_name = metric_format % {
                'name': name,
                'channel': self.channel_name(channels[index]),
                'metric': metrics[index],
            }
            yield metric_name, metrics[index]


    def channel_name(self, channel):
        channel = channel.lower()
        channel = re.sub(r'[ -]+', '_', channel)
        channel = re.sub(r'[^a-z0-9_]', '', channel)
        return channel

    def format_downstream(self, data):
        metric_format = 'modem.downstream.%(name)s.%(channel)s'
        metrics = []
        channels = [
            'frequency',
            'lock_status',
            'channel',
            'modulation',
            'symbol_rate',
            'interleave',
            'power',
            'rx_mer',
        ]
        for index, channel in enumerate(channels, 1):
            metrics.extend(self.metric_table(
                metric_format, channel, data[0], data[index]))
        return metrics

    def format_upstream(self, data):
        metric_format = 'modem.upstream.%(name)s.%(channel)s'
        metrics = []
        channels = [
            'channel_type',
            'channel',
            'frequency',
            'ranging_status',
            'modulation',
            'symbol_rate',
            'mini_slot_size',
            'power',
            'timeouts.t1',
            'timeouts.t2',
            'timeouts.t3',
            'timeouts.t4',
        ]
        for index, channel in enumerate(channels, 1):
            metrics.extend(self.metric_table(
                metric_format, channel, data[0], data[index]))
        return metrics

    def format_usburst(self, data):
        metric_format = 'modem.upstream.%(channel)s.%(name)s'
        metrics = []
        channels = [
            'modulation',
            'differential_encoding',
            'preamble.size',
            'preamble.offset',
            'fec_error_correction',
            'fec_codeword_bytes',
            'max_burst_size',
            'guard_time_size',
            'last_codeword_length',
            'scrambler_state',
        ]
        for index, channel in enumerate(channels, 1):
            metrics.extend(self.metric_table(
                metric_format, channel, data[0], data[index]))
        return metrics

    def format_configuration(self, data):
        return [
            ('modem.configuration.network_access', data[0][1]),
            ('modem.configuration.cpe_number', data[1][1]),
            ('modem.configuration.baseline_privacy', data[2][1]),
            ('modem.configuration.docsis_mode', data[3][1]),
            ('modem.configuration.config_file', data[4][1]),
        ]

    def strip_units(self, value):
        known_units = ('Hz', 'dB', 'dBmV')
        if value.endswith(known_units):
            value, unit = value.strip().split(' ', 1)
        return value

    def publish_stats(self, client, metric):
        pass

    @controller.expose(hide=True)
    def default(self):
        stats_client = None
        if self.app.pargs.statsd:
            stats_client = statsd.StatsClient(
                prefix=self.app.pargs.statsd_prefix)
        for page in STATUS_PAGES:
            soup = self.fetch_page(page)
            caption, data = self.process_table(soup.table)
            if hasattr(self, 'format_' + page):
                data = getattr(self, 'format_' + page)(data)
            for name, value in data:
                value = self.strip_units(value)
                print('%s %s' % (name, self.strip_units(value)))
                if stats_client:
                    try:
                        stats_client.gauge(name, float(value))
                    except ValueError:
                        pass

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
