# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""CLI entry point for the shared bounded RSS/Atom reader."""
from spikes.rss_reader import MAX_BYTES, fetch, main, observe, parse_feed

if __name__ == '__main__':
    main()
