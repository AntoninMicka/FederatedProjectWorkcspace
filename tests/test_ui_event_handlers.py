# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""AUDIT-B7-T1: async UI handlers must not read event.currentTarget after an await.

The browser resets ``event.currentTarget`` to null once dispatch ends, so a
handler that re-enables its button after ``await`` threw a TypeError and left
the button disabled (found by tests/test_ui_chat_browser.py). This is a static
guard over every page script; the behaviour itself is tested in the browser.
"""
import re
import unittest

HANDLER = re.compile(r"addEventListener\('(\w+)',async (?:event|\(event\))=>\{")
NESTED = re.compile(r"(?:\(event\)|\bevent)=>\{")


def closing_brace(text, start):
    depth, index = 1, start
    while depth and index < len(text):
        if text[index] == '{':
            depth += 1
        elif text[index] == '}':
            depth -= 1
        index += 1
    return index - 1


def late_current_target_reads(script):
    """Line numbers of async handlers that read event.currentTarget after an await."""
    found = []
    for match in HANDLER.finditer(script):
        body = script[match.end():closing_brace(script, match.end())]
        for nested in NESTED.finditer(body):  # inner handlers have their own event
            end = closing_brace(body, nested.end())
            body = body[:nested.start()] + ' ' * (end - nested.start()) + body[end:]
        first_await = body.find('await ')
        if first_await >= 0 and 'event.currentTarget' in body[first_await:]:
            found.append(script[:match.start()].count('\n') + 1)
    return found


class AsyncHandlerTests(unittest.TestCase):
    def test_no_async_handler_reads_current_target_after_await(self):
        from spikes.desktop_management import ASSETS
        from spikes.web_server import ASSETS as WEB_ASSETS
        for name, assets in (('desktop', ASSETS), ('web', WEB_ASSETS)):
            with self.subTest(runtime=name):
                self.assertEqual(late_current_target_reads(assets['/app.js'][1]), [])

    def test_guard_detects_the_bug_it_prevents(self):
        broken = ("button.addEventListener('click',async event=>{event.currentTarget.disabled=true;"
                  "await work();event.currentTarget.disabled=false;});")
        fixed = ("button.addEventListener('click',async event=>{const eventTarget=event.currentTarget;"
                 "eventTarget.disabled=true;await work();eventTarget.disabled=false;});")
        nested = ("a.addEventListener('click',async event=>{await work();"
                  "b.addEventListener('change',event=>{event.currentTarget.value='';});});")
        self.assertEqual(late_current_target_reads(broken), [1])
        self.assertEqual(late_current_target_reads(fixed), [])
        self.assertEqual(late_current_target_reads(nested), [])


if __name__ == '__main__':
    unittest.main()
