# For whoever runs the streaming server

Nothing in here is part of the app. It is the one file a server sometimes
needs before "Who is listening" (`Ctrl+Shift+A`) can say anything.

## status-json.xsl

Icecast publishes its own statistics at `/status-json.xsl`: what the mounts
are, what is playing on each and how many people are listening. It is the
same information the public status page shows, it needs no password, and
that is what Drop Deck reads.

Some Icecast installs do not ship the file, and a request for it then gets
`404 Could not parse XSLT file`, which looks exactly like a server that has
no statistics rather than one that is missing a file. Tony's own was one of
these.

Copy it into the Icecast web root and it works at once. No restart, no
config change:

    scp status-json.xsl you@your-server:/path/to/icecast/web/
    ssh you@your-server chmod 644 /path/to/icecast/web/status-json.xsl

Then `http://your-server:8000/status-json.xsl` should answer with JSON.

One deliberate difference from the file Icecast ships with: that one emits a
bare object when there is exactly one mount and an array when there is more
than one, so every client has to handle both shapes and most handle only the
second. This always emits an array. Drop Deck reads either.

## If your listeners are somewhere else

You do not need this file at all if your listeners are on a server Drop Deck
can already reach. It looks at the address you stream to, then at the same
host on port 8000, which covers a station that streams into automation and
serves its audience from the Icecast behind it. If neither is right, put the
address in **Where listeners connect** on the Streaming tab.
