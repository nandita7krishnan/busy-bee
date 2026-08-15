## busy-bee status tracking

Every project on this machine is tracked by busy-bee (a menu bar
dashboard across side projects). Before doing anything else in a
session, confirm `dashctl` is on PATH (`which dashctl`); if it's
missing, skip the rest of this section and mention it in your response
once. No setup is needed beyond that -- the current directory
auto-registers itself the first time any command below runs.

Log status as you work, using one-line, plain-language descriptions:

- Finished a task: `dashctl done "<what you finished>"`
- Identified upcoming work: `dashctl todo "<what's next>"`
- Can't proceed without the user: `dashctl blocker "<what's blocking you>"`
- Need a decision from the user: `dashctl question "<the question>"`
- A blocker or question got resolved: `dashctl resolve blocker <id>` or
  `dashctl resolve question <id>` (the id is printed when it was logged)

Log at least one item before ending a turn -- a `done` if you finished
something, a `todo` if you're mid-task, or a `blocker`/`question` if
you're stuck. A Stop hook will remind you if you forget.
