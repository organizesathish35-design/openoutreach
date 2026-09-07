"""The sheet console's own CLI.

    python -m sheetflow find 5          find 5 leads, buy addresses (1 credit each), store in the sheet
    python -m sheetflow find 5 --free   ...without buying addresses (no credits)
    python -m sheetflow draft           AI writes a personalized draft into the sheet for each row
    python -m sheetflow send            send every row you marked Approved = YES
"""
from __future__ import annotations

import argparse
import sys

from .steps import cmd_draft, cmd_find, cmd_send


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="sheetflow",
        description="Lead finding, AI drafting and approval-gated sending, with a "
                    "Google Sheet as the review screen.",
    )
    verbs = parser.add_subparsers(dest="verb", required=True)

    find = verbs.add_parser("find", help="find leads and store them in the sheet")
    find.add_argument("goal", type=int, help="how many leads to find")
    find.add_argument("--free", action="store_true",
                      help="do not buy email addresses (no credits spent)")

    draft = verbs.add_parser("draft", help="AI-draft emails into the sheet")
    draft.add_argument("--limit", type=int, default=None, help="stop after this many drafts")

    send = verbs.add_parser("send", help="send rows with Approved = YES")
    send.add_argument("--limit", type=int, default=10, help="max emails this run (default 10)")

    options = parser.parse_args(argv)
    if options.verb == "find":
        if options.goal < 1:
            sys.exit("sheetflow: find takes a number of leads, e.g. `python -m sheetflow find 5`")
        return cmd_find(options.goal, free=options.free)
    if options.verb == "draft":
        return cmd_draft(limit=options.limit)
    return cmd_send(limit=options.limit)


if __name__ == "__main__":
    sys.exit(main())
