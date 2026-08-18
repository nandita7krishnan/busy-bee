## busy-bee status tracking

Every project on this machine is tracked by busy-bee (a menu bar
dashboard across side projects). Before doing anything else in a
session, confirm `dashctl` is on PATH (`which dashctl`); if it's
missing, skip the rest of this section and mention it in your response
once. No setup is needed beyond that -- the current directory
auto-registers itself the first time any command below runs.

Log status as you work, using one-line, plain-language descriptions.
**Keep every line short -- aim for under 12 words, one clause, no
sub-clauses.** The dashboard has limited space and these are meant to
be scannable at a glance, not a changelog entry. If what you did needs
more than one clause to explain, log the outcome only and leave the
reasoning/detail out -- it's in your own conversation already.

  - Good: `dashctl done "fixed the login redirect loop"`
  - Too verbose: `dashctl done "found and fixed a bug where the login
    redirect loop was caused by a stale session cookie not being
    cleared on logout, which I traced through the auth middleware and
    fixed by adding an explicit cookie expiry"`

- Finished a task: `dashctl done "<what you finished>"`
- Identified upcoming work: `dashctl todo "<what's next>"` (note its
  id -- once you actually do it, resolve it, see below)
- Can't proceed without the user: `dashctl blocker "<what's blocking you>"`
- Need a decision from the user: `dashctl question "<the question>"`
- A blocker, question, or todo you logged manually is done: `dashctl
  resolve blocker|question|todo <id>` (the id is printed when it was
  logged). Without this, a manually-logged todo just sits there
  forever instead of clearing -- don't forget it once the work is
  actually done. (Items synced from TodoWrite don't need this --
  that's handled automatically.)
- Wrapping up a chunk of work, or a session is ending: `dashctl summary
  "<one sentence on where things stand>"`. This is different from the
  above -- it doesn't add to a growing list, it's a single line shown
  next to the project name, overwritten each time. Keep it very short.
  Every 10th turn (starting with the first), the Stop hook requires
  this one specifically, not just any item -- don't wait for a natural
  wrap-up point on those turns.

If the TodoWrite tool is available and used, its list is synced into
dashctl automatically via a hook -- no need to separately call
`dashctl todo` for the same items already tracked there.

Log at least one item before ending a turn -- a `done` if you finished
something, a `todo` if you're mid-task, or a `blocker`/`question` if
you're stuck. A Stop hook will remind you if you forget.
