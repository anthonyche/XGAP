package xgap.fuseki;

import java.security.SecureRandom;
import java.util.HexFormat;
import java.util.Map;
import java.util.Objects;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import org.apache.jena.sparql.exec.QueryExec;

/** Dataset/principal-bound leases. Acknowledgement waits for query lifecycle exit. */
public final class OwnedQueries {
    private final Map<String, Lease> leases = new ConcurrentHashMap<>();
    private final SecureRandom random = new SecureRandom();
    public synchronized String register(String dataset, String principal) {
        long now = System.nanoTime();
        leases.entrySet().removeIf(e -> e.getValue().expired(now));
        if (leases.size() >= 4096) throw new IllegalStateException("Owned query registry full");
        byte[] bytes = new byte[32]; random.nextBytes(bytes);
        String handle = HexFormat.of().formatHex(bytes);
        leases.put(handle, new Lease(dataset, principal, now));
        return handle;
    }
    public Lease get(String handle, String dataset, String principal) {
        Lease lease = handle == null ? null : leases.get(handle);
        if (lease == null || !Objects.equals(dataset, lease.dataset) || !Objects.equals(principal, lease.principal))
            throw new IllegalArgumentException("Unknown owned query handle");
        return lease;
    }
    public static final class Lease {
        final String dataset, principal;
        final long created;
        final CountDownLatch ended = new CountDownLatch(1);
        boolean started, cancelled, finished;
        QueryExec query;
        Lease(String dataset, String principal, long created) {
            this.dataset=dataset; this.principal=principal; this.created=created;
        }
        synchronized boolean expired(long now) {
            return (!started || finished) && now-created>TimeUnit.MINUTES.toNanos(10);
        }
        public synchronized void begin() {
            if (started || cancelled || expired(System.nanoTime())) throw new IllegalStateException("Query lease unavailable");
            started=true;
        }
        public synchronized void attach(QueryExec execution) {
            if (!started || finished || query!=null) throw new IllegalStateException("Invalid query lifecycle");
            query=execution;
            if (cancelled) query.abort();
        }
        public synchronized void finished() {
            // Called only AFTER QueryExec close and dataset read-transaction end.
            finished=true; query=null; ended.countDown();
        }
        public boolean cancel(long waitMillis) throws InterruptedException {
            synchronized(this) {
                cancelled=true;
                if (!started) { finished=true; ended.countDown(); }
                if (query!=null) query.abort();
            }
            return ended.await(waitMillis, TimeUnit.MILLISECONDS);
        }
    }
}
