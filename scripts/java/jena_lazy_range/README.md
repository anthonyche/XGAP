# Experimental read-only Jena range overlay

Derived from Apache Jena 5.6.0 `BPTreeRangeIterator.java` (Apache-2.0; included
LICENSE.txt). Apache Jena is Copyright 2011–2025 The Apache Software Foundation.
Upstream source:
https://github.com/apache/jena/blob/jena-5.6.0/jena-db/jena-dboe-trans-data/src/main/java/org/apache/jena/dboe/trans/bplustree/BPTreeRangeIterator.java

XGAP modification, 2026-09-24: the range traversal snapshots child page IDs in
the existing block read scope, then fetches each page only when consumed, under
a balanced block read scope. Range bounds, comparator, result order and caller
MVCC transaction are retained. This avoids eagerly reading unused range pages
before an upper LIMIT terminates iteration.

This is **not upstream Jena** and is **not a default online backend**. It is an
opt-in, pinned overlay for offline failed-request diagnosis on immutable private
store copies. The engine JAR is unchanged. It must not silently replace an
official baseline deployment or claim to be a planner contribution. Any later
formal adoption requires an explicit shared backend contract and provenance.

Provenance checks:

- Original class in the frozen JAR: SHA-256
  `cd48a47afe150e1b4cd2a8645e8c6ad6b6d1d758d7bf1708bdae6d17c80f696d`.
- Upstream text retrieved via the web reader (line labels removed, LF): SHA-256
  `02a5e2105bde547159b10dc93cbc37f7a7b1151e0c49c8b404fad09a4c2e657a`.
- Compiled upstream text has identical resolved javap instructions to the pinned
  class, ignoring constant-pool ordinals/debug line tables. No original methods
  were replaced from a different release.

`XgapRangeCheck` checks 108 ranges against an independent integer oracle,
including misses, exclusive upper bounds, deletion and exhaustion. It also
checks a real TDB reader spanning a concurrent writer commit, rollback and reopen.
The page-get count is a logical block-manager read count, including cache hits;
it is not physical disk pages, bytes, elapsed time or a formal speedup.
