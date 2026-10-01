# Experimental read-only Jena range overlay

Derived from Apache Jena 5.6.0 `BPTreeRangeIterator.java` and
`BPTreeRangeIteratorMapper.java` (Apache-2.0; included
LICENSE.txt). Apache Jena is Copyright 2011–2025 The Apache Software Foundation.
Upstream source:
https://github.com/apache/jena/blob/jena-5.6.0/jena-db/jena-dboe-trans-data/src/main/java/org/apache/jena/dboe/trans/bplustree/BPTreeRangeIterator.java

Mapped tuple path:
https://github.com/apache/jena/blob/jena-5.6.0/jena-db/jena-dboe-trans-data/src/main/java/org/apache/jena/dboe/trans/bplustree/BPTreeRangeIteratorMapper.java

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
- Mapped original class SHA-256:
  `8dfbaeb5bec7a7c9312f87467a50b15634c0000bb98ddb88f4b96704ea7538c2`;
  normalized upstream text SHA-256:
  `2cefed31e9cb694a0328c29c3b44fa84ae16b437e3caa1048573721627051f59`.
  Its original compiled instructions also match. The mapped path calls the same
  lazy-page helper; an offline counter attests actual mapped-iterator creation.

The initial v1 overlay covered only ordinary records; diagnostic 3864057 still
used the upstream mapped tuple path and timed out. v2 covers both paths. Merely
loading one modified class is not proof of active query-path coverage.

`XgapRangeCheck` checks 108 ranges on EACH path against an independent integer oracle,
including misses, exclusive upper bounds, deletion and exhaustion. It also
checks a real TDB reader spanning a concurrent writer commit, rollback and reopen.
The page-get count is a logical block-manager read count, including cache hits;
it is not physical disk pages, bytes, elapsed time or a formal speedup.
