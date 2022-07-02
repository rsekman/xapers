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
import sys
import logging
import collections

import urwid

from ..database import Database
from .search import Search, Document, PALETTE as SEARCHPALETTE
from . import bibview
from .config import Config, Key, Action
from .interactable import KeyHandler, Interactable, InteractableMeta


if os.getenv('XAPERS_LOG_FILE'):
    logging.basicConfig(filename=os.getenv('XAPERS_LOG_FILE'),
                        level=logging.DEBUG)


PALETTE = [
    ('header', 'light gray', 'dark blue'),
    ('header_args', 'white', 'dark blue'),
    ('footer', 'light gray', 'dark blue'),
    ('footer_error', 'white', 'dark red'),
    ('prompt', 'black', 'dark green'),
    ]


class PromptEdit(urwid.Edit, metaclass=urwid.signals.MetaSignals):
    signals = ['done']

    def __init__(self, prompt, initial=None, completions=None, history=None):
        super(PromptEdit, self).__init__(caption=prompt)
        if initial:
            self.insert_text(initial)
        self.completions = completions
        self.completion_data = {}
        self.history = history
        self.history_pos = -1
        self.last_text = ''

    def keypress(self, size, key):
        if self.last_text and self.edit_text != self.last_text:
            self.completion_data.clear()
            self.history_pos = -1

        if key == 'enter':
            urwid.emit_signal(self, 'done', self.get_edit_text())
            return
        elif key in ['esc', 'ctrl g']:
            urwid.emit_signal(self, 'done', None)
            return

        # navigation
        elif key == 'ctrl a':
            # move to beginning
            key = 'home'
        elif key == 'ctrl e':
            # move to end
            key = 'end'
        elif key == 'ctrl b':
            # back character
            self.set_edit_pos(self.edit_pos-1)
        elif key == 'ctrl f':
            # forward character
            self.set_edit_pos(self.edit_pos+1)
        elif key == 'meta b':
            # back word
            text = self.edit_text
            pos = self.edit_pos - 1
            inword = False
            while True:
                try:
                    text[pos]
                except IndexError:
                    break
                if text[pos] != ' ' and not inword:
                    inword = True
                    continue
                if inword:
                    if text[pos] == ' ':
                        break
                pos -= 1
            self.set_edit_pos(pos+1)
        elif key == 'meta f':
            # forward word
            text = self.edit_text
            pos = self.edit_pos
            inword = False
            while True:
                try:
                    text[pos]
                except IndexError:
                    break
                if text[pos] != ' ' and not inword:
                    inword = True
                    continue
                if inword:
                    if text[pos] == ' ':
                        break
                pos += 1
            self.set_edit_pos(pos+1)

        # deletion
        elif key == 'ctrl d':
            # delete character
            text = self.edit_text
            pos = self.edit_pos
            ntext = text[:pos] + text[pos+1:]
            self.set_edit_text(ntext)
        elif key == 'ctrl k':
            # delete to end
            self.set_edit_text(self.edit_text[:self.edit_pos])

        # history
        elif key in ['up', 'ctrl p']:
            if self.history:
                if self.history_pos == -1:
                    self.history_full = self.history + [self.edit_text]
                try:
                    self.history_pos -= 1
                    self.set_edit_text(self.history_full[self.history_pos])
                    self.set_edit_pos(len(self.edit_text))
                except IndexError:
                    self.history_pos += 1
        elif key in ['down', 'ctrl n']:
            if self.history:
                if self.history_pos != -1:
                    self.history_pos += 1
                    self.set_edit_text(self.history_full[self.history_pos])
                    self.set_edit_pos(len(self.edit_text))

        # tab completion
        elif key == 'tab' and self.completions:
            # tab complete on individual words

            # retrieve current text and position
            text = self.edit_text
            pos = self.edit_pos

            # find the completion prefix
            tpos = pos - 1
            while True:
                try:
                    if text[tpos] == ' ':
                        tpos += 1
                        break
                except IndexError:
                    break
                tpos -= 1
            prefix = text[tpos:pos]
            # FIXME: this prefix stripping should not be done here
            prefix = prefix.lstrip('+-')
            # find the end of the word
            tpos += 1
            while True:
                try:
                    if text[tpos] == ' ':
                        break
                except IndexError:
                    break
                tpos += 1

            # record/clear completion data
            if self.completion_data:
                # clear the data if the prefix is new
                if prefix != self.completion_data['prefix']:
                    self.completion_data.clear()
                # otherwise rotate the queue
                else:
                    self.completion_data['q'].rotate(-1)
            else:
                self.completion_data['prefix'] = prefix
                # harvest completions
                q = collections.deque()
                for c in self.completions:
                    if c.startswith(prefix):
                        q.append(c)
                self.completion_data['q'] = q

            logging.debug(self.completion_data)

            # insert completion at point
            if self.completion_data and self.completion_data['q']:
                c = self.completion_data['q'][0][len(prefix):]
                ntext = text[:pos] + c + text[tpos:]
                self.set_edit_text(ntext)
                self.set_edit_pos(pos)

        # record the last text
        self.last_text = self.edit_text
        return super(PromptEdit, self).keypress(size, key)

class UI(Interactable, urwid.Frame, metaclass=InteractableMeta):

    default_status_string = "s: new search, q: close buffer, Q: quit, ?: help"
    buffers = []
    search_history = []
    tag_history = []

    def __init__(self, db, cmd=None):
        urwid.Frame.__init__(self, urwid.SolidFill)
        self.db = db

        self.config = Config()

        # FIXME: set this properly
        self.palette = list(set(PALETTE) | set(SEARCHPALETTE))

        self.set_status()

        self.mainloop = urwid.MainLoop(
            self,
            self.palette,
            unhandled_input=lambda x: x,
            handle_mouse=False,
            )
        self.mainloop.screen.set_terminal_properties(colors=88)

        if not cmd:
            cmd = ['search', 'tag:new']
        self.newbuffer(cmd)

        self.mainloop.run()

    def write_db(self):
        return Database(self.db.root, writable=True)

    ##########

    def set_status(self, text=None, error=False):
        if text:
            T = [urwid.Text(text)]
        else:
            T = [('pack', urwid.Text('Xapers [{}]'.format(len(self.buffers)))),
                 urwid.Text(self.default_status_string, align='right'),
            ]
        if error:
            palette = 'footer_error'
        else:
            palette = 'footer'
        self.set_footer(urwid.AttrMap(urwid.Columns(T), palette))

    def newbuffer(self, cmd):
        if not cmd:
            cmd = ['search', '*']

        if cmd[0] == 'search':
            query = cmd[1]
            buf = search.Search(self, query)
        elif cmd[0] == 'bibview':
            query = cmd[1]
            buf = bibview.Bibview(self, query)
        elif cmd[0] == 'help':
            buf = Help(self.config)
        else:
            buf = Help(self.config)
            self.set_status("Unknown command '%s'." % (cmd[0]))
        self.buffers.append(buf)
        self.set_body(buf)
        self.set_status()

    def prompt(self, final, *args, **kwargs):
        """user prompt

        final is a (func, args) tuple to be executed upon complection:
        func(text, *args)

        further args and kwargs are passed to PromptEdit

        """
        pe = PromptEdit(*args, **kwargs)
        urwid.connect_signal(pe, 'done', self.prompt_done, final)
        self.set_footer(urwid.AttrMap(pe, 'prompt'))
        self.set_focus('footer')

    def prompt_done(self, text, final):
        self.set_focus('body')
        urwid.disconnect_signal(self, self.prompt, 'done', self.prompt_done)
        (func, args) = final
        func(text, *args)

    def promptSearch_done(self, query):
        if not query:
            self.set_status()
            return
        self.newbuffer(['search', query])

    ##########
    # Key handlers
    ##########

    @KeyHandler
    def promptSearch(self, size, key):
        """search database"""
        prompt = 'search: '
        self.prompt((self.promptSearch_done, []),
                    prompt, history=self.search_history)

    @KeyHandler
    def quit(self, size, key):
        """quit"""
        sys.exit()

    @KeyHandler
    def help(self, size, key):
        """help"""
        self.newbuffer(['help', self.buffers[-1]])

    @KeyHandler
    def killBuffer(self, size, key):
        """close current buffer"""
        if len(self.buffers) == 1:
            return
        self.buffers.pop()
        buf = self.buffers[-1]
        self.set_body(buf)
        self.set_status()
        self.mainloop.draw_screen()

class Help(urwid.Frame):
    def __init__(self, config):

        htxt = [urwid.Text("Help")]
        header = urwid.AttrMap(urwid.Columns(htxt), "header")

        pile = []

        # format command help line
        def fch(key, cmd, hlp):
            return urwid.Columns(
                [
                    ("fixed", 10, urwid.Text(key)),
                    ("fixed", 20, urwid.Text(cmd)),
                    urwid.Text(hlp),
                ]
            )

        def addline(key, cmd, hlp):
            if not key:
                pile.append(urwid.Text(""))
                pile.append(urwid.Text(""))
                pile.append(urwid.Text(hlp))
                pile.append(urwid.Text(""))
            else:
                pile.append(fch(key, cmd, hlp))
        for w in Interactable.__subclasses__():
            for k, cmd, h in w._help(config):
                addline(k, cmd, h)

        body = urwid.ListBox(urwid.SimpleListWalker(pile))

        super(Help, self).__init__(body, header=header)

    def keypress(self, size, key):
        # ignore help in help
        if key == "?":
            return
        if key == " ":
            return self.get_body().keypress(size, "page down")
        return super(Help, self).keypress(size, key)

    def help(self):
        return []
