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
import pkgutil


class ParseError(Exception):
    pass


def parse_data(data):
    """Parse binary data of specified mime type into text (str)

    """
    for (loader, name, ispkg) in pkgutil.walk_packages(__path__):
        if ispkg:
            continue
        module = loader.find_module(name).load_module(name)
        try:
            return module.parse(data)
        except:
            pass
    raise ParseError("Could not parse file.")


def parse_file(path):
    """Parse file for text (str)

    """

    # FIXME: determine mime type

    if not os.path.exists(path):
        raise ParseError(f"File not found: {path}")

    if not os.path.isfile(path):
        raise ParseError(f"File is not a regular file: {path}")

    with open(path, 'br') as f:
        data = f.read()

    return parse_data(data)
