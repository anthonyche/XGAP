package xgap.fuseki;
import org.apache.jena.sparql.exec.QueryExec;
import org.apache.jena.sparql.core.DatasetGraphFactory;
import java.util.concurrent.*;

/** No HTTP listener or server process: real in-memory Jena execution lifecycle. */
public final class OwnedQueriesTest {
    public static void main(String[] args) throws Exception {
        OwnedQueries registry=new OwnedQueries();
        String handle=registry.register("/data","alice");
        try { registry.get(handle,"/data","bob"); throw new AssertionError("cross-user handle accepted"); }
        catch (IllegalArgumentException expected) {}
        try { registry.get(handle,"/other","alice"); throw new AssertionError("cross-dataset handle accepted"); }
        catch (IllegalArgumentException expected) {}
        OwnedQueries.Lease lease=registry.get(handle,"/data","alice");
        lease.begin();
        var dataset=DatasetGraphFactory.createTxnMem();
        dataset.begin(org.apache.jena.query.ReadWrite.READ);
        try (QueryExec query=QueryExec.dataset(dataset).query("SELECT * WHERE { VALUES ?x {1 2 3} }").build()) {
            lease.attach(query);
            if (lease.cancel(0)) throw new AssertionError("Acknowledged before query close/transaction end");
            try { query.select().hasNext(); throw new AssertionError("Aborted query kept executing"); }
            catch (org.apache.jena.query.QueryCancelledException expected) {}
        } finally { dataset.end(); lease.finished(); }
        if (!lease.cancel(0)) throw new AssertionError("No completion acknowledgement");
        var before=registry.get(registry.register("/data",null),"/data",null);
        if (!before.cancel(0)) throw new AssertionError("Unstarted cancellation not confirmed");
        try { before.begin(); throw new AssertionError("Cancelled lease executed"); }
        catch (IllegalStateException expected) {}
        var pending=registry.get(registry.register("/data",null),"/data",null);
        pending.begin(); pending.cancel(0);
        try (QueryExec query=QueryExec.dataset(dataset).query("ASK {}").build()) {
            pending.attach(query);
            try { query.ask(); throw new AssertionError("Registration race allowed query"); }
            catch (org.apache.jena.query.QueryCancelledException expected) {}
        } finally { pending.finished(); }
        System.out.println("Owned cancellation: ownership, pre-dispatch race, real Jena abort, post-close acknowledgement PASS");
    }
}
