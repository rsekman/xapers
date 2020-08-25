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
along with notmuch.  If not, see <https://www.gnu.org/licenses/>.

Copyright 2012-2020
Jameson Rollins <jrollins@finestructure.net>
"""

import os
import sys
import signal
import argparse
import shutil

import readline

from .version import __version__
from .database import (
    Database,
    DatabaseUninitializedError,
    DatabaseInitializationError,
    DatabaseError,
)
from .documents import Document
from .sources import Sources, SourceError, SourceAttributeError
from .parsers import parse_data, ParseError
from .bibtex import Bibtex, BibtexError
from . import nci


PROG = 'xapers'

XAPERS_ROOT = \
    os.path.abspath(
        os.path.expanduser(
            os.getenv(
                'XAPERS_ROOT',
                os.path.join('~', '.xapers', 'docs')
            )
        )
    )

LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()

########################################################################


def initdb(writable=False, create=False, force=False):
    try:
        return Database(XAPERS_ROOT, writable=writable, create=create, force=force)
    except DatabaseUninitializedError as e:
        print(e, file=sys.stderr)
        sys.exit("Import a document to initialize.")
    except DatabaseInitializationError as e:
        print(e, file=sys.stderr)
        sys.exit("Either clear the directory and add new files, or use 'retore' to restore from existing data.")
    except DatabaseError as e:
        sys.exit(e)


class QueryAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        query_string = ' '.join(values)
        if query_string == '+':
            query_string = '*'
        setattr(namespace, self.dest, query_string)


def add_query_arg(parser, required=True, single=False, default=None):
    help = "search query"
    if required:
        nargs = '+'
    else:
        nargs = '*'
    if single:
        help += " (must match a single document)"
    parser.add_argument(
        'query',
        metavar='SEARCH-TERM',
        #nargs=argparse.REMAINDER,
        nargs=nargs,
        default=default,
        action=QueryAction,
        help=help
    )


class SourceFile:
    @staticmethod
    def parse(data):
        try:
            return parse_data(data)
        except ParseError as e:
            print(f"Parse error: {e}", file=sys.stderr)
            print("Is file a PDF?", file=sys.stderr)
            sys.exit(1)

    def __init__(self, name, data):
        self.name = name
        self.data = data
        self.text = SourceFile.parse(data)

    @classmethod
    def read(cls, fobj):
        name = os.path.basename(fobj.name)
        data = fobj.read()
        return cls(name, data)


class Completer:
    def __init__(self, words):
        self.words = words

    def terms(self, prefix, index):
        matching_words = [
            w for w in self.words if w.startswith(prefix)
            ]
        try:
            return matching_words[index]
        except IndexError:
            return None


def prompt_for_file(infile):
    if infile:
        print(f"file: {infile}", file=sys.stderr)
    else:
        readline.set_startup_hook()
        readline.parse_and_bind('')
        readline.set_completer()
        infile = input('file: ')
        if infile == '':
            infile = None
    return infile


def prompt_for_source(sources):
    if sources:
        readline.set_startup_hook(lambda: readline.insert_text(sources[0].sid))
    readline.parse_and_bind("tab: complete")
    completer = Completer(sources)
    readline.set_completer(completer.terms)
    readline.set_completer_delims(' ')
    source = input('source: ')
    if source == '':
        source = None
    return source


def prompt_for_tags(db, tags):
    # always prompt for tags, and append to initial
    if tags:
        print("initial tags: {}".format(' '.join(tags)), file=sys.stderr)
    else:
        tags = []
    if db:
        itags = list(db.term_iter('tag'))
    else:
        itags = None
    readline.set_startup_hook()
    readline.parse_and_bind("tab: complete")
    completer = Completer(itags)
    readline.set_completer(completer.terms)
    readline.set_completer_delims(' ')
    while True:
        tag = input('tag: ')
        if tag and tag != '':
            tags.append(tag.strip())
        else:
            break
    return tags


def print_doc_summary(doc):
    docstr = doc.docstr
    title = doc.get_title() or ''
    tags = ' '.join(sorted(doc.get_tags()))
    sources = ' '.join(doc.get_sids())
    key = doc.get_key()
    if not key:
        key = ''
    print(f'{docstr} [{sources}] {{{key}}} ({tags}) "{title}"')

########################################################################


def cmd_add(parser, args=None):
    """add document to database

Any provided files will be indexed, and specified sources will be used
to retrieve bibtex.  If interactive mode is specified
('--interactive'), the user will be prompted for additional
information if needed and will be presented with the curses UI of the
resultant entry upon completion.

    """
    if args is None:
        parser.add_argument(
            '--file', '-f',
            type=argparse.FileType('rb'),
            help="file to index",
        )
        parser.add_argument(
            '--source', '-s', metavar='SID',
            help="source ID for online retrieval of bibtex, or bibtex file path",
        )
        parser.add_argument(
            '--tags', '-t', metavar='TAG[,TAG...]',
            help="initial tags for document, comma separated",
        )
        parser.add_argument(
            '--interactive', '-i', action='store_true',
            help="interactively prompt user for feedback",
        )
        add_query_arg(parser, required=False, single=True)
        return

    if not args.source and not args.file:
        parser.error("Must specify either source or file to add.")

    db = initdb(writable=True, create=True)
    doc = None
    dfile = None
    source = None
    bibtex = None

    # get existing doc from query string
    if args.query:
        if db.count(args.query) != 1:
            print("Search did not match a single document.", file=sys.stderr)
            sys.exit("Aborting.")
        for doc in db.search(args.query):
            break
    else:
        doc = Document(db)

    # load the file
    if args.file:
        dfile = SourceFile.read(args.file)
        similar = list(db.find_similar(dfile.text))
        if similar:
            print("Document appears to already be in the database:", file=sys.stderr)
            for doc, score in similar:
                print_doc_summary(doc)
            if args.interactive:
                response = input("continue? [y|N]: ")
                if response.lower() not in ['y', 'yes']:
                    sys.exit("Aborting.")
            else:
                sys.exit("Aborting.")

    # scan for sources
    if args.interactive and dfile and not args.source:
        print("Scanning document for source identifiers...", file=sys.stderr)
        doc_sources = Sources().scan_text(dfile.text)
        nsources = len(doc_sources)
        desc = "source ID" if nsources == 1 else "source IDs"
        print(f"{nsources} {desc} found:", file=sys.stderr)
        for source in doc_sources:
            print(f"  {source}", file=sys.stderr)
        args.source = prompt_for_source(doc_sources)
        args.tags = prompt_for_tags(db, args.tags)

    # parse source
    if args.source:
        if os.path.exists(args.source):
            bibtex = args.source

        else:
            source = Sources().match_source(args.source)
            if not source:
                sys.exit(f"String '{args.source}' matches no known source.")

            sdoc = db.doc_for_source(source.sid)
            if db.doc_for_source(source.sid):
                print("A document already exists for specified source:", file=sys.stderr)
                print_doc_summary(sdoc)
                sys.exit("Aborting.")

            try:
                print("Retrieving bibtex...", end=' ', file=sys.stderr, flush=True)
                bibtex = source.fetch_bibtex()
                print("done.", file=sys.stderr)
            except SourceError as e:
                print("FAILED.", file=sys.stderr)
                sys.exit(f"Could not retrieve bibtex: {e}")

            if not args.file:
                try:
                    print("Retrieving file...", end=' ', file=sys.stderr, flush=True)
                    dfile = SourceFile(*source.fetch_file())
                    print("done.", file=sys.stderr)
                except SourceAttributeError:
                    print(f"File download not available for {source.name} source.", file=sys.stderr)
                except SourceError as e:
                    print("FAILED.", file=sys.stderr)
                    print(f"Could not retrieve file: {e}", file=sys.stderr)

    if bibtex:
        try:
            print("Adding bibtex...", end=' ', file=sys.stderr, flush=True)
            doc.add_bibtex(bibtex)
            print("done.", file=sys.stderr)
        except BibtexError as e:
            print("FAILED.", file=sys.stderr)
            print(e, file=sys.stderr)
            print("Bibtex must be a plain text file with a single bibtex entry.", file=sys.stderr)
            sys.exit(1)
        except:
            print("FAILED.", file=sys.stderr)
            raise

    # add source sid if it hasn't been added yet
    if source and not doc.get_sids():
        doc.add_sid(source.sid)

    if dfile:
        try:
            print("Adding file...", end=' ', file=sys.stderr, flush=True)
            doc.add_file_data(dfile.name, dfile.data)
            print("done.", file=sys.stderr)
        except parser.ParseError as e:
            print("FAILED.", file=sys.stderr)
            print(f"Parse error: {e}", file=sys.stderr)
            sys.exit(1)
        except:
            print("FAILED.", file=sys.stderr)
            raise

    if args.tags:
        try:
            print("Adding tags...", end=' ', file=sys.stderr, flush=True)
            doc.add_tags(args.tags.split(','))
            print("done.", file=sys.stderr)
        except:
            print("FAILED.", file=sys.stderr)
            raise

    # sync the doc to db and disk
    try:
        print("Syncing document...", end=' ', file=sys.stderr)
        doc.sync()
        print("done.\n", end=' ', file=sys.stderr)
    except:
        print("FAILED", file=sys.stderr)
        raise

    print_doc_summary(doc)

    if args.interactive and doc:
        nci.UI(cmd=['search', doc.docstr])


def cmd_import(parser, args=None):
    """import all entries from a bibtex database

    """
    if args is None:
        parser.add_argument(
            'bibfile',
            help="bibtex database file to import (FIXME: '-' for stdin)",
        )
        parser.add_argument(
            '--tags', '-t', metavar='TAG[,TAG...]',
            help="tags to apply to created entries",
        )
        parser.add_argument(
            '--overwrite', action='store_true',
            help="overwrite FIXME",
        )
        return

    db = initdb(writable=True, create=True)
    errors = []
    sources = Sources()

    for entry in sorted(Bibtex(args.bibfile), key=lambda entry: entry.key):
        print(entry.key, file=sys.stderr)

        try:
            docs = []

            # check for doc with this bibkey
            bdoc = db.doc_for_bib(entry.key)
            if bdoc:
                docs.append(bdoc)

            # check for known sids
            for source in sources.scan_bibentry(entry):
                sdoc = db.doc_for_source(source.sid)
                # FIXME: why can't we match docs in list?
                if sdoc and sdoc.docid not in [doc.docid for doc in docs]:
                    docs.append(sdoc)

            if len(docs) == 0:
                doc = Document(db)
            elif len(docs) > 0:
                if len(docs) > 1:
                    print("  Multiple distinct docs found for entry.  Using first found.", file=sys.stderr)
                doc = docs[0]
                print(f"  Updating {doc.docstr}...", file=sys.stderr)

            doc.add_bibentry(entry)

            filepath = entry.get_file()
            if filepath:
                print(f"  Adding file: {filepath}", file=sys.stderr)
                doc.add_file(filepath)

            doc.add_tags(args.tags.split(','))

            doc.sync()

        except BibtexError as e:
            print(f"  Error processing entry {entry.key}: {e}", file=sys.stderr)
            print(file=sys.stderr)
            errors.append(entry.key)

    if errors:
        print(file=sys.stderr)
        print("Failed to import {:d}".format(len(errors)), end=' ', file=sys.stderr)
        if len(errors) == 1:
            print("entry", end=' ', file=sys.stderr)
        else:
            print("entries", end=' ', file=sys.stderr)
        print("from bibtex:", file=sys.stderr)
        for error in errors:
            print("  "+error, file=sys.stderr)
        sys.exit(1)
    else:
        sys.exit(0)


def cmd_update(parser, args=None):
    """update FIXME

    """
    if args is None:
        add_query_arg(parser, required=True, single=True)
        return

    with initdb(writable=True) as db:
        for doc in db.search(args.query):
            try:
                print(f"Updating {doc.docstr}...", end=' ', file=sys.stderr)
                doc.update_from_bibtex()
                doc.sync()
                print("done.", file=sys.stderr)
            except:
                print("FAILED", file=sys.stderr)
                raise


def cmd_tag(parser, args=None):
    """add/remove document tags

Tags should be a comma-separated list of tag operations to perform on
all documents matching the supplied search.  Operations are of the
form "[OP]TAG" where OP is the operator ('+' to add, '-' to remove)
and TAG is the tag string itself.  If no operator is specified the tag
will be added.  For example, the following command will add the tags
'foo' and 'bar' and remove the tag 'baz':

  xapers tag +foo,bar,-baz ...

If the initial operator is to be '-', prefix the operator with a comma
(',') to not confuse the argument parser, e.g.:

  xapers tag ,-foo ...

(Suggestions for how to get around this annoyance with python argparse
would be much appreciated.)

    """
    if args is None:
        parser.add_argument(
            'tags', metavar='[OP]TAG[,[OP]TAG...]',
            help="comma-separated list of tag operations",
        )
        add_query_arg(parser, required=True)
        return

    add_tags = []
    remove_tags = []
    for tag in args.tags.strip(',').split(','):
        if tag[0] == '-':
            remove_tags.append(tag[1:])
        elif tag[0] == '+':
            add_tags.append(tag[1:])
        else:
            add_tags.append(tag)

    with initdb(writable=True) as db:
        doc = None
        for doc in db.search(args.query):
            doc.add_tags(add_tags)
            doc.remove_tags(remove_tags)
            doc.sync()
        if not doc:
            sys.exit("No matching documents, no tags applied.")


def cmd_delete(parser, args=None):
    """delete documents from the database

    """
    if args is None:
        parser.add_argument(
            '--force', action='store_true',
            help="do not prompt for confirmation",
        )
        add_query_arg(parser, required=True, single=True)
        return

    with initdb(writable=True) as db:
        count = db.count(args.query)
        if count == 0:
            print("No documents found for query.", file=sys.stderr)
            sys.exit(1)
        for doc in db.search(args.query):
            if not args.force:
                print("The following document will be deleted:.", file=sys.stderr)
                print_doc_summary(doc)
                resp = input("Type 'yes' to confirm: ")
                if resp != 'yes':
                    sys.exit("Aborting.")
            print(f"deleting {doc.docstr}...", end=' ', file=sys.stderr, flush=True)
            doc.purge()
            print("done.", file=sys.stderr)


def cmd_search(parser, args=None):
    """search database for documents

See "xapers help search-terms" for more information on search query
syntax.

    """
    if args is None:
        parser.add_argument(
            '--output', '-o',
            choices=['summary', 'bibtex', 'sources', 'keys', 'tags', 'files'], default='summary',
            help="what information to output [summary]",
        )
        parser.add_argument(
            '--sort', '-s',
            choices=['relevance', 'year'], default='relevance',
            help="sort output by relevance score or publication year [relevance]",
        )
        parser.add_argument(
            '--limit', '-l', metavar='N', type=int, default=0,
            help="limit number of returned results ('0' is no limit) [0]",
        )
        add_query_arg(parser, required=True)
        return

    oset = set()

    for doc in initdb().search(args.query, sort=args.sort, limit=args.limit):
        if args.output == 'summary':
            print_doc_summary(doc)

        elif args.output == 'bibtex':
            if bibtex := doc.get_bibtex():
                print(bibtex)
                print()
            else:
                print(f"No bibtex for doc {doc.docstr}.", file=sys.stderr)

        elif args.output == 'sources':
            for source in doc.get_sids():
                print(source)

        elif args.output == 'keys':
            if key := doc.get_key():
                print(key)

        elif args.output == 'tags':
            oset |= set(doc.get_tags())

        elif args.output == 'files':
            for path in doc.get_fullpaths():
                print(path)

    if oset:
        for item in sorted(oset):
            print(item)


def cmd_tags(parser, args=None):
    """short for "search --output tags"

Search of entire database is assumed if no query is provided.

    """
    if args is None:
        add_query_arg(parser, required=False, default='*')
        return

    args.output = 'tags'
    args.sort = 'relevance'
    args.limit = 0
    cmd_search(parser, args)


def cmd_bibtex(parser, args=None):
    """short for "search --output bibtex"

Search of entire database is assumed if no query is provided.

    """
    if args is None:
        add_query_arg(parser, required=False, default='*')
        return

    args.output = 'bibtex'
    args.sort = 'year'
    args.limit = 0
    cmd_search(parser, args)


def cmd_count(parser, args=None):
    """print number of documents matching search

    """
    if args is None:
        add_query_arg(parser, required=False, default='*')
        return

    print(initdb().count(args.query))


def cmd_view(parser, args=None):
    """view search results in curses UI

    """
    if args is None:
        add_query_arg(parser, required=False, default=['tag:new'])
        return

    nci.UI(initdb(), cmd=['search', args.query])


def cmd_similar(parser, args=None):
    """find documents similar to file

    """
    if args is None:
        parser.add_argument(
            'file', type=argparse.FileType('rb'),
            help="file path",
        )
        return

    dfile = SourceFile.read(args.file)
    for doc, score in initdb().find_similar(dfile.text):
        # FIXME: show score somehow?
        print_doc_summary(doc)


def cmd_export(parser, args=None):
    """export document files to a directory

Copy all files from documents matching search into the specified
directory.

    """
    if args is None:
        parser.add_argument(
            'dir',
            help="export directory",
        )
        add_query_arg(parser, required=True)
        return

    try:
        os.makedirs(args.dir)
    except:
        pass

    # FIXME: why?
    import pipes

    for doc in initdb().search(args.query):
        title = doc.get_title()
        origpaths = doc.get_fullpaths()
        nfiles = len(origpaths)
        for i, path in enumerate(origpaths):
            if not title:
                name = os.path.basename(os.path.splitext(path)[0])
            else:
                name = title.replace(' ', '_')
            if nfiles > 1:
                name += f'.{i}'
            name += '.pdf'
            outpath = os.path.join(args.dir, name)
            print(outpath)
            shutil.copyfile(path, outpath.encode('utf-8'))


def cmd_restore(parser, args=None):
    """restore database

This restores the database from an existing Xapers data directory.
This is usually only needed if the database has become corrupted for
some reason.

    """
    if args is None:
        return

    with initdb(writable=True, create=True, force=True) as db:
        db.restore(log=True)


def cmd_db(parser, args=None):
    """database utilities

    """
    if args is None:
        subparser = parser.add_subparsers(
            title="commands",
            dest='cmd',
            required=True,
            #metavar='',
        )
        sp_dump = subparser.add_parser(
            'dump',
            help="dump terms from db or document",
            description="dump terms from db or document",
        )
        sp_dump.add_argument(
            '--prefix', '-p',
            help="filter for specific prefix",
        )
        add_query_arg(sp_dump, required=False, default='*')
        subparser.add_parser(
            'maxid',
            help="return max docid",
            description="return max docid",
        )
        return

    if args.cmd == 'dump':
        with initdb() as db:
            if args.query == '*':
                for term in db.term_iter(args.prefix):
                    print(term)
            else:
                terms = set()
                for doc in db.search(args.query):
                    terms |= set(doc.term_iter(args.prefix))
                for term in terms:
                    print(term)

    else:
        docid = 0
        with initdb() as db:
            for doc in db.search('*'):
                docid = max(docid, doc.docid)
            print(f"id:{docid}")


def cmd_source(parser, args=None):
    """source utilities

See the README included with xapers for more information on sources,
including how to create custom sources.

    """
    if args is None:
        def add_sid_arg(parser):
            parser.add_argument(
                'source', metavar='SOURCE_ID',
                help="source ID ('SOURCE:ID' or URL)",
            )
        subparser = parser.add_subparsers(
            title="commands",
            dest='cmd',
            required=True,
            #metavar='',
        )
        subparser.add_parser(
            'list',
            help="list known sources",
            description="list known sources",
        )
        sp_url = subparser.add_parser(
            'url',
            help="resolve URL for source and print",
            description="resolve URL for source and print",
        )
        add_sid_arg(sp_url)
        sp_bib = subparser.add_parser(
            'bib',
            help="retrieve bibtex for source and print",
            description="retrieve bibtex for source and print",
        )
        sp_bib.add_argument(
            '--raw', action='store_true',
            help="print bibtex without processing",
        )
        add_sid_arg(sp_bib)
        sp_file = subparser.add_parser(
            'file',
            help="retrieve file for source and write to stdout",
            description="retrieve file for source and write to stdout",
        )
        add_sid_arg(sp_file)
        sp_scan = subparser.add_parser(
            'scan',
            help="scan file for source IDs",
        )
        sp_scan.add_argument(
            'file', metavar='FILE', type=argparse.FileType('rb'),
            help="file to scan",
        )
        return

    sources = Sources()

    def get_source(sid):
        item = sources.match_source(sid)
        if not item:
            sys.exit(f"String '{sid}' matches no known source.")
        return item

    if args.cmd == 'list':
        for source in sources:
            if source.is_builtin:
                path = 'builtin'
            else:
                path = source.path
            print(f"{source.name}: {source.description} ({source.url}) [{path}]")

    elif args.cmd == 'url':
        print(get_source(args.source).url)

    elif args.cmd == 'bib':
        try:
            bibtex = get_source(args.source).fetch_bibtex()
        except SourceError as e:
            sys.exit(f"Could not retrieve file: {e}")
        if args.raw:
            print(bibtex)
        else:
            try:
                print(Bibtex(bibtex)[0].as_string())
            except:
                print("Failed to parse retrieved bibtex data.", file=sys.stderr)
                print("Use --raw option to view raw retrieved data.", file=sys.stderr)
                sys.exit(1)

    elif args.cmd == 'file':
        source = get_source(args.source)
        try:
            sfile = SourceFile(*source.fetch_file())
        except SourceError as e:
            sys.exit(f"Could not retrieve file: {e}")
        print(sfile.data)

    elif args.cmd == 'scan':
        try:
            sfile = SourceFile.read(args.file)
        except ParseError as e:
            print(f"Parse error: {e}", file=sys.stderr)
            print("Is file a PDF?", file=sys.stderr)
            sys.exit(1)
        for item in sources.scan_text(sfile.text):
            print(item)


def cmd_help(parser, args=None):
    """Xapers help

    """
    if args is None:
        parser.add_argument(
            'cmd', metavar="'search-terms'", nargs='?',
            help="show search query syntax help",
        )
        return

    if args.cmd == 'search-terms':
        print("""
Xapers supports a common syntax for search terms.

Search can consist of free-form text and quoted phrases.  Terms can be
combined with standard Boolean operators.  All terms are combined with
a logical AND by default.  Parentheses can be used to group operators,
but must be protect from shell interpretation.  The strings '*' and
'+' will match all documents.

Additionally, the following prefixed terms are understood (where
<brackets> indicate user-supplied values):

   id:<docid>                document ID
   title:<string>            string in title (also t:)
   author:<string>           string in authors (also a:)
   tag:<tag>                 user tag
   <source>:<id>             source ID (sid)
   source:<source>           source
   key:<key>                 bibtex citation key
   year:<year>               publication year or range (also y:)
   year:<since>..<until>
   year:..<until>
   year:<since>..

Publication years must be four-digit integers.

See the following for more information on search terms:

  https://xapian.org/docs/queryparser.html
""".strip())

    else:
        parser.print_help()

##################################################


def get_func(cmd):
    return eval('cmd_{}'.format(cmd))


parser = argparse.ArgumentParser(
    prog=PROG,
    description="""Personal journal article management and indexing system""",
    epilog=f"""
The path to the xapers document store may be specified with the
XAPERS_ROOT environment variable, and defaults to the following if not
specified (the directory is allowed to be a symlink):

  {XAPERS_ROOT}

See "xapers help search-terms" for more information on term
definitions and search syntax.
""",
    formatter_class=argparse.RawDescriptionHelpFormatter,
)
parser.add_argument(
    '--version', '-v', action='version', version=__version__,
    help="show version number and exit",
)
subparsers = parser.add_subparsers(
    title="commands",
    dest='cmd',
    required=True,
    metavar='',
)


def gensubparse(cmd, *aliases, prefix_chars='-'):
    func = get_func(cmd)
    sp = subparsers.add_parser(
        cmd, aliases=aliases,
        help=func.__doc__.splitlines()[0].strip(),
        description=func.__doc__.strip(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        prefix_chars=prefix_chars,
    )
    func(sp)
    sp.set_defaults(func=func)


gensubparse('add')
gensubparse('import')
gensubparse('tag')
gensubparse('delete')
gensubparse('search')
gensubparse('tags')
gensubparse('bibtex')
gensubparse('count')
gensubparse('view', 'show')
gensubparse('similar')
gensubparse('export')
gensubparse('restore')
gensubparse('db')
gensubparse('source', 'sources')
gensubparse('help')


def main():
    args = parser.parse_args()
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    if LOG_LEVEL == 'DEBUG':
        print(args)
    args.func(parser, args)


if __name__ == '__main__':
    main()
