"""
This file is part of xapers.

Xapers is free software: you can redistribute it and/or modify it
under the terms of the GNU General Public License as published by the
Free Software Foundation, either version 3 of the License, or (at your
option) any later version.

Xapers is distributed in the hope that it will be useful, but WITHOUT
ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License
for more details.

You should have received a copy of the GNU General Public License
along with xapers.  If not, see <https://www.gnu.org/licenses/>.

Copyright 2012-2020
Jameson Rollins <jrollins@finestructure.net>
"""

import os
import re
import pkgutil

from urllib.parse import urlparse


XAPERS_SOURCE_PATH = [os.path.expanduser(os.path.join('~', '.xapers', 'sources'))]
if os.getenv('XAPERS_SOURCE_PATH'):
    XAPERS_SOURCE_PATH += os.getenv('XAPERS_SOURCE_PATH').split(':')
XAPERS_SOURCE_PATH += __path__

##################################################


class SourceError(Exception):
    pass


class SourceAttributeError(SourceError):
    def __init__(self, source, msg):
        self.source = source
        self.msg = msg

    def __str__(self):
        return "Source '{}' does not implement the {}.".format(self.source.name, self.msg)

##################################################


class Source(object):
    """Xapers class representing an online document source.

    The Source object is build from a source nickname (name) and
    possibly user-defined source module.

    """
    def __init__(self, name, module):
        self.name = name
        self.module = module

    def __repr__(self):
        return '<Xapers {} {}>'.format(
            self.__class__.__name__, self.name)

    def __str__(self):
        return self.name

    def __getitem__(self, id):
        return SourceItem(self, id)

    @property
    def path(self):
        return self.module.__file__

    @property
    def is_builtin(self):
        bpath = os.path.dirname(__file__)
        spath = os.path.dirname(self.path)
        return os.path.commonprefix([bpath, spath]) == bpath

    @property
    def description(self):
        try:
            return self.module.description
        except AttributeError:
            raise SourceAttributeError(self, "'description' property")

    @property
    def url(self):
        try:
            return self.module.url
        except AttributeError:
            raise SourceAttributeError(self, "'url' property")

    @property
    def url_regex(self):
        try:
            return self.module.url_regex
        except AttributeError:
            raise SourceAttributeError(self, "'url_regex' property")

    @property
    def scan_regex(self):
        try:
            return self.module.scan_regex
        except AttributeError:
            raise SourceAttributeError(self, "'scan_regex' property")

    def fetch_bibtex(self, id):
        try:
            func = self.module.fetch_bibtex
        except AttributeError as e:
            raise SourceAttributeError(self, "fetch_bibtex() function") from e
        return func(id)

    def fetch_file(self, id):
        try:
            func = self.module.fetch_file
        except AttributeError as e:
            raise SourceAttributeError(self, "fetch_file() function") from e
        return func(id)


class SourceItem(Source):
    """Xapers class representing an item from an online source.

    """
    def __init__(self, source, id):
        super().__init__(source.name, source.module)
        self.id = id
        self.sid = '{}:{}'.format(self.name, self.id)

    def __repr__(self):
        return '<Xapers {} {}>'.format(
            self.__class__.__name__, self.sid)

    def __str__(self):
        return self.sid

    def __hash__(self):
        return hash(self.sid)

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return self.sid == other.sid
        return NotImplemented

    def __ne__(self, other):
        return not self.__eq__(other)

    def __str__(self):
        return self.sid

    @property
    def url(self):
        try:
            return self.module.url_format % self.id
        except AttributeError:
            raise SourceAttributeError(self, "'url_format' property")

    def fetch_bibtex(self):
        return super(SourceItem, self).fetch_bibtex(self.id)

    def fetch_file(self):
        return super(SourceItem, self).fetch_file(self.id)

##################################################


class Sources(object):
    def __init__(self):
        self._sources = {}
        for (loader, name, ispkg) in pkgutil.walk_packages(XAPERS_SOURCE_PATH):
            if ispkg:
                continue
            #self._modules[name] = loader.find_module(name).load_module(name)
            module = loader.find_module(name).load_module(name)
            self._sources[name] = Source(name, module)

    def __repr__(self):
        return '<Xapers {} {}>'.format(self.__class__, XAPERS_SOURCE_PATH)

    def get_source(self, name, id=None):
        try:
            source = self._sources[name]
        except KeyError:
            raise SourceError(f"unknown source: {name}")
        if id:
            return source[id]
        else:
            return source

    def __contains__(self, source):
        return source in self._sources

    def __getitem__(self, sid):
        name = None
        id = None
        try:
            vals = sid.split(':')
        except ValueError:
            raise SourceError("could not parse sid string")
        name = vals[0]
        if len(vals) > 1:
            id = vals[1]
        return self.get_source(name, id)

    def __iter__(self):
        return iter(self._sources.values())

    def match_source(self, string):
        """Return Source object from URL or source identifier string.

        Return None for no match.

        """
        o = urlparse(string)

        # if the scheme is http, look for source match
        if o.scheme in ['http', 'https']:
            for source in self:
                try:
                    regex = source.url_regex
                except SourceAttributeError:
                    # FIXME: warning?
                    continue
                match = re.match(regex, string)
                if match:
                    return source[match.group(1)]

        elif o.scheme != '' and o.path != '':
            return self.get_source(o.scheme, o.path)

    def scan_text(self, text):
        """Scan text for source identifiers

        Source 'scan_regex' attributes are used.
        Returns a list of SourceItem objects.

        """
        items = set()
        for source in self:
            try:
                regex = re.compile(source.scan_regex)
            except SourceAttributeError:
                # FIXME: warning?
                continue
            matches = regex.findall(text)
            if not matches:
                continue
            for match in matches:
                items.add(source[match])
        return list(items)

    def scan_bibentry(self, bibentry):
        """Scan bibentry for source identifiers.

        Bibentry keys are searched for source names, and bibentry
        values are assumed to be individual identifier strings.
        Returns a list of SourceItem objects.

        """
        fields = bibentry.get_fields()
        items = set()
        for field, value in fields.items():
            field = field.lower()
            if field in self:
                items.add(self.get_source(field, value))
        # FIXME: how do we get around special exception for this?
        if 'eprint' in fields:
            items.add(self.get_source('arxiv', fields['eprint']))
        return list(items)
