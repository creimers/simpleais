from collections import defaultdict
import functools
import os
import sys

import click
import numpy

from . import sentences_from_source
import re


TIME_FORMAT = "%Y/%m/%d %H:%M:%S"


def print_sentence_source(text, file=sys.stdout):
    if isinstance(text, str):
        print(text, file=file)
    else:
        for line in text:
            print(line, file=file)


def sentences_from_sources(sources):
    if len(sources) > 0:
        for source in sources:
            for sentence in sentences_from_source(source):
                yield sentence
    else:
        for sentence in sentences_from_source(sys.stdin):
            yield sentence


@click.command()
@click.argument('sources', nargs=-1)
@click.option('--mmsi', '-m', multiple=True)
@click.option('--mmsi-file', '-f')
@click.option('--type', '-t', 'sentence_type', type=int)
@click.option('--latitude', '--lat', nargs=2, type=float)
@click.option('--longitude', '--long', '--lon', nargs=2, type=float)
def grep(sources, mmsi, mmsi_file=None, sentence_type=None, lat=None, lon=None):
    if mmsi_file:
        mmsi = list(mmsi)
        with open(mmsi_file, "r") as f:
            mmsi.extend([l.strip() for l in f.readlines()])
        mmsi = frozenset(mmsi)
    for sentence in sentences_from_sources(sources):
        factors = [True]

        if len(mmsi) > 0:
            factors.append(sentence['mmsi'] in mmsi)
        if sentence_type:
            factors.append(sentence.type_id() == sentence_type)
        if lat:
            factors.append(sentence['lat'] and lat[0] < sentence['lat'] < lat[1])
        if lon:
            factors.append(sentence['lon'] and lon[0] < sentence['lon'] < lon[1])

        if functools.reduce(lambda x, y: x and y, factors):
            print_sentence_source(sentence.text)


@click.command()
@click.argument('sources', nargs=-1)
def as_text(sources):
    for sentence in sentences_from_sources(sources):
        result = []
        result.append(sentence.time.strftime(TIME_FORMAT))
        result.append("{:2}".format(sentence.type_id()))
        result.append("{:9}".format(str(sentence['mmsi'])))
        if sentence['lat']:
            result.append("{:9.4f} {:9.4f}".format(sentence['lat'], sentence['lon']))
        elif sentence.type_id() == 5:
            result.append("{}->{}".format(sentence['shipname'], sentence['destination']))

        print(" ".join(result))


@click.command()
@click.argument('source', nargs=1)
@click.argument('dest', nargs=1, required=False)
def burst(source, dest):
    if not dest:
        dest = source
    writers = {}
    fname, ext = os.path.splitext(dest)

    for sentence in sentences_from_source(source):
        mmsi = sentence['mmsi']
        if not mmsi:
            mmsi = 'other'
        if mmsi not in writers:
            writers[mmsi] = open("{}-{}{}".format(fname, mmsi, ext), "wt")
        print_sentence_source(sentence.text, writers[mmsi])

    for writer in writers.values():
        writer.close()


class Fields:
    def __init__(self):
        self.values = {}

    def __getitem__(self, key):
        return self.values[key]

    def __setitem__(self, key, value):
        value = value.strip()
        if key and value and len(value) > 0:
            self.values[key] = value

    def __iter__(self):
        return self.values.__iter__()


class SenderInfo:
    def __init__(self):
        self.mmsi = None
        self.sentence_count = 0
        self.type_counts = defaultdict(int)
        self.fields = Fields()

    def add(self, sentence):
        if not self.mmsi:
            self.mmsi = sentence['mmsi']
        self.sentence_count += 1
        self.type_counts[sentence.type_id()] += 1
        if sentence.type_id() == 5:
            self.fields['shipname'] = sentence['shipname']
            self.fields['destination'] = sentence['destination']

    def report(self):
        print("{}:".format(self.mmsi))
        print("    sentences: {}".format(self.sentence_count))
        type_text = ["{}: {}".format(t, self.type_counts[t]) for t in (sorted(self.type_counts))]
        print("        types: {}".format(", ".join(type_text)))
        for field in sorted(self.fields):
            print("  {:>11s}: {}".format(field, self.fields[field]))


class MaxMin:
    def __init__(self, starting=None):
        self.min = self.max = starting

    def valid(self):
        return self.min is not None and self.min is not None

    def add(self, value):
        if not self.valid():
            self.min = self.max = value
            return
        if value > self.max:
            self.max = value
        if value < self.min:
            self.min = value


class GeoInfo:
    def __init__(self):
        self.lat = MaxMin()
        self.lon = MaxMin()

    def add(self, latitude, longitude):
        self.lat.add(latitude)
        self.lon.add(longitude)

    def report(self, indent=""):
        print("{}    top left: {}, {}".format(indent, self.lat.max, self.lon.min))
        print("{}bottom right: {}, {}".format(indent, self.lat.min, self.lon.max))

    def __str__(self, *args, **kwargs):
        return "GeoInfo(latmin={}, latmax={}, lonmin={}, lonmax={})".format(self.lat.min, self.lat.max,
                                                                            self.lon.min, self.lon.max)

    def valid(self):
        return self.lat.valid() and self.lon.valid()


class SentencesInfo:
    def __init__(self):
        self.sentence_count = 0
        self.type_counts = defaultdict(int)
        self.sender_counts = defaultdict(int)
        self.geo_info = GeoInfo()

    def add(self, sentence):
        self.sentence_count += 1
        self.type_counts[sentence.type_id()] += 1
        self.sender_counts[sentence['mmsi']] += 1
        if sentence['lat']:
            self.geo_info.add(sentence['lat'], sentence['lon'])

    def report(self):
        print("Found {} senders in {} sentences.".format(len(self.sender_counts), self.sentence_count))
        print("   type counts:")
        for i in sorted(self.type_counts):
            print("                {:2d} {:8d}".format(i, self.type_counts[i]))
        print()
        self.geo_info.report("  ")


class Bucketer:
    """Given min, max, and buckets, buckets values"""

    def __init__(self, min_val, max_val, bucket_count):
        self.min_val = min_val
        self.max_val = max_val
        self.bucket_count = bucket_count
        self.max_buckets = bucket_count - 1
        if self.min_val == self.max_val:
            self.bins = numpy.linspace(min_val - 1, max_val + 1, bucket_count + 1)
        else:
            self.bins = numpy.linspace(min_val, max_val + sys.float_info.epsilon, bucket_count + 1)

    def bucket(self, value):
        result = numpy.digitize(value, self.bins) - 1

        # this shouldn't be necessary, but it somehow is
        if result > self.max_buckets:
            return self.max_buckets
        return result

    def __str__(self, *args, **kwargs):
        return "Bucketer({}, {}, {}, {})".format(self.min_val, self.max_val, self.bucket_count, self.bins)


class DensityMap:
    def __init__(self, width=60, height=20, indent=""):
        self.width = width
        self.height = height
        self.indent = indent
        self.geo_info = GeoInfo()
        self.points = []

    def add(self, latitude, longitude):
        self.points.append((latitude, longitude))
        self.geo_info.add(latitude, longitude)

    def to_counts(self):
        # noinspection PyUnusedLocal
        results = [[0 for ignored in range(self.width)] for ignored in range(self.height)]
        if self.geo_info.valid():
            xb = Bucketer(self.geo_info.lon.min, self.geo_info.lon.max, self.width)
            yb = Bucketer(self.geo_info.lat.min, self.geo_info.lat.max, self.height)
            for lat, lon in self.points:
                x = xb.bucket(lon)
                y = self.height - 1 - yb.bucket(lat)
                results[y][x] += 1
        return results

    def to_text(self):
        counts = self.to_counts()

        max_count = max([max(l) for l in counts])

        def value_to_text(value):
            if value == 0:
                return " "
            return str(int((9.99999) * value / max_count))

        output = []
        output.append("{}+{}+".format(self.indent, "-" * self.width))
        for row in counts:
            output.append("{}|{}|".format(self.indent, "".join([value_to_text(col) for col in row])))
        output.append("{}+{}+".format(self.indent, "-" * self.width))
        return output

    def show(self):
        print("\n".join(self.to_text()))


@click.command()
@click.argument('sources', nargs=-1)
@click.option('--individual', '-i', is_flag=True)
@click.option('--map', '-m', "show_map", is_flag=True)
def info(sources, individual, show_map):
    sentences_info = SentencesInfo()
    sender_info = defaultdict(SenderInfo)
    map_info = DensityMap()

    for sentence in sentences_from_sources(sources):
        sentences_info.add(sentence)
        if show_map:
            if sentence['lat']:
                map_info.add(sentence['lat'], sentence['lon'])
        if individual:
            sender_info[sentence['mmsi']].add(sentence)

    sentences_info.report()
    if show_map:
        map_info.show()

    if individual:
        for mmsi in sorted(sender_info):
            sender_info[mmsi].report()


def chunks(l, n):
    """Yield successive n-sized chunks from l."""
    for i in range(0, len(l), n):
        yield l[i:i + n]


PAT = re.compile("!(A.*)\*(..)")
# based on https://en.wikipedia.org/wiki/NMEA_0183
def checksum_check(fragment_text):
    m = PAT.search(fragment_text)
    calculated = hex(functools.reduce(lambda a,b: a^b, [ord(c) for c in m.group(1)]))[2:4]
    return m.group(2) == calculated.upper()

def checksum_checks(sentence):
    if isinstance(sentence.text, str):
        return [checksum_check(sentence.text)]
    else:
        return [checksum_check(t) for t in sentence.text]

@click.command()
@click.argument('sources', nargs=-1)
def dump(sources):
    sentence_count = 0
    for sentence in sentences_from_sources(sources):
        if sentence_count != 0:
            print()
        sentence_count += 1
        print("Sentence {}:".format(sentence_count))
        if sentence.time:
            print("   time: {}".format(sentence.time.strftime(TIME_FORMAT)))
        print("   type: {}".format(sentence.type_id()))
        print("   MMSI: {}".format(sentence['mmsi']))
        bit_lumps = list(chunks(str(sentence.message_bits()), 6))
        groups = chunks(bit_lumps, 10)
        print("  check: {}".format(", ".join([str(c) for c in checksum_checks(sentence)])))
        print("   bits: {}".format(" ".join(groups.__next__())))
        for group in groups:
            print("         {}".format(" ".join(group)))
