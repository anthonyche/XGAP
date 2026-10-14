package xgap.fuseki;

import java.io.IOException;
import org.apache.jena.atlas.json.JSON;
import org.apache.jena.atlas.json.JsonObject;
import org.apache.jena.fuseki.main.FusekiServer;
import org.apache.jena.fuseki.server.Operation;
import org.apache.jena.fuseki.servlets.*;
import org.apache.jena.query.Query;
import org.apache.jena.sparql.core.DatasetGraph;
import org.apache.jena.sparql.exec.QueryExec;

/** Explicit embedding extension; ordinary Fuseki endpoints are unchanged. */
public final class ConfirmedCancellation {
    private ConfirmedCancellation() {}
    public static FusekiServer.Builder install(FusekiServer.Builder builder, String dataset) {
        OwnedQueries registry=new OwnedQueries();
        Operation query=Operation.alloc("urn:xgap:owned-query", "xgap-owned-query", "Owned read-only query");
        Operation control=Operation.alloc("urn:xgap:owned-control", "xgap-owned-control", "Owned cancellation acknowledgement");
        builder.registerOperation(query,new QueryService(registry));
        builder.registerOperation(control,new ControlService(registry));
        builder.addEndpoint(dataset,"xgap-query",query);
        builder.addEndpoint(dataset,"xgap-control",control);
        return builder;
    }
    static final class QueryService extends SPARQL_QueryDataset {
        final OwnedQueries registry;
        QueryService(OwnedQueries registry) { this.registry=registry; }
        OwnedQueries.Lease lease(HttpAction action) {
            return registry.get(action.getRequestHeader("X-XGAP-Handle"),action.getDatasetName(),action.getUser());
        }
        @Override protected void executeLifecycle(HttpAction action) {
            OwnedQueries.Lease owned;
            try { owned=lease(action); owned.begin(); }
            catch (IllegalArgumentException | IllegalStateException e) { ServletOps.errorBadRequest(e.getMessage()); return; }
            try { super.executeLifecycle(action); }
            finally { owned.finished(); }
        }
        @Override protected QueryExec createQueryExec(HttpAction action, Query query, DatasetGraph dataset) {
            QueryExec execution=super.createQueryExec(action,query,dataset);
            try { lease(action).attach(execution); return execution; }
            catch (RuntimeException e) { execution.close(); throw e; }
        }
    }
    static final class ControlService extends ActionService {
        final OwnedQueries registry;
        ControlService(OwnedQueries registry) { this.registry=registry; }
        @Override public void execPost(HttpAction action) { executeLifecycle(action); }
        @Override public void validate(HttpAction action) {}
        @Override public void execute(HttpAction action) {
            try {
                byte[] bytes=action.getRequestInputStream().readNBytes(8193);
                if (bytes.length>8192) { ServletOps.errorBadRequest("Control request too large"); return; }
                JsonObject input=JSON.parse(new String(bytes,java.nio.charset.StandardCharsets.UTF_8));
                JsonObject output=new JsonObject();
                if ("register".equals(input.getString("action"))) {
                    output.put("handle",registry.register(action.getDatasetName(),action.getUser()));
                } else if ("cancel".equals(input.getString("action"))) {
                    String handle=input.getString("handle");
                    boolean ended=registry.get(handle,action.getDatasetName(),action.getUser()).cancel(3000);
                    output.put("handle",handle); output.put("backend_termination_confirmed",ended);
                } else { ServletOps.errorBadRequest("Unknown control action"); return; }
                ServletOps.sendJson(action,output);
            } catch (InterruptedException e) { Thread.currentThread().interrupt(); ServletOps.error(503,"Cancellation interrupted"); }
            catch (IOException | IllegalArgumentException | IllegalStateException e) { ServletOps.errorBadRequest(e.getMessage()); }
        }
    }
}
