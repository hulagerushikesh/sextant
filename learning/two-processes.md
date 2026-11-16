# Two processes, one library

*2026-11-16. Found by the owner's first self-test in Claude Desktop.*

## What happened

After reinstalling the extension as 0.11.0, every sextant tool in Claude
Desktop failed with a bare "Error executing tool". The server's log had the
cause on each call: Chroma could not open the store —
*"Failed to apply logs to the hnsw segment writer"*.

Claude Desktop's own log shows it **launches the server twice** for one
extension, through two different paths, a second apart. Both processes stay
alive and either may be sent a tool call. On 2026-11-15 both of them indexed
the same Downloads folder into the same store at the same time — the
server's log has the line "141 stored, 14 unchanged, 35 not indexed" twice.
Chroma's on-disk store is not safe to write from two processes. The damage did
not show until a fresh process opened the store a day later.

A copy of the owner's store fails the same way on this Mac with the same
Chroma (1.5.9): 5,595 chunks in its database, 5,507 vectors in its index, and
242 log entries that cannot be applied to it.

## Reproduced

Two processes, each replacing the same 100 documents of 40 chunks (delete the
old chunks, then add the new ones, as the folder pass does), started together:
in one round of four the store would not open afterwards, with the same error;
in two others the opening process printed nothing (not examined).
Two processes writing *different* documents did not break it in three rounds,
and one process writing after another had written did not either.

The first idea was a lock around each document's writes. With that, a store
still broke: opening it afterwards hung (checked again on a copy: still hung
after 20 seconds). Each process keeps its own copy of the vector index in
memory, so taking turns is not enough. Closing and reopening the client before
each turn did not fix it either: in one of six rounds the process opening the
store afterwards crashed.

## The fix

Exactly one process opens the store (`sextant/vector_db/sharing.py`):

- The first process to take a lock file beside the store holds it for its
  lifetime, listens on a local socket (127.0.0.1, with a random token in a
  file only this user can read), indexes the chosen folder, and answers tool
  calls.
- Every other process forwards each tool call to it and returns the answer
  unchanged. `kb_stats` → `server_process` shows which process answered: the
  same one for every client of one library.
- When the owner exits, the operating system drops its lock and the next
  process to need the library takes over.
- `sextant-ingest` and `sextant-forget` open the store themselves, so they
  refuse while a server holds it.

And a store Chroma cannot read is **moved aside** (`<store>.unreadable-<time>`),
not deleted, and a new one opened. The folder is indexed again from its files;
anything added another way stays in the moved copy, and `kb_stats` →
`set_aside` says so. Tried on a copy of the owner's store: moved, and a new
empty store opened.

## Checked

- Two real servers over one folder: one indexes it, both answer with the same
  process, search works through either, and the store opens afterwards.
- Three rounds of two servers re-indexing all 525 files of a test folder
  together: every round answered by one process, the store opened each time.
- Each part planted back and caught: tools not forwarded, the library always
  answered locally, both processes indexing, no set-aside.

## Not proven

- That Claude Desktop sends calls to both processes — only that it starts
  both and keeps both alive. The fix does not depend on which one it uses.
- Damage that makes Chroma hang or crash rather than raise an error is not
  caught; only an error is. Both were seen in the reproduction, before the fix.
- Windows: the lock and the socket are portable, but nothing here ran there.
