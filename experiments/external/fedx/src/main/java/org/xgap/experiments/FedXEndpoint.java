package org.xgap.experiments;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.URI;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.util.List;
import java.util.concurrent.Executors;
import org.eclipse.rdf4j.federated.FedXConfig;
import org.eclipse.rdf4j.federated.FedXFactory;
import org.eclipse.rdf4j.query.QueryLanguage;
import org.eclipse.rdf4j.query.BindingSet;
import org.eclipse.rdf4j.query.resultio.TupleQueryResultParserRegistry;
import org.eclipse.rdf4j.query.resultio.sparqljson.SPARQLResultsJSONParserFactory;
import org.eclipse.rdf4j.query.resultio.sparqljson.SPARQLResultsJSONWriter;
import org.eclipse.rdf4j.query.resultio.sparqlxml.SPARQLResultsXMLParserFactory;
import org.eclipse.rdf4j.repository.Repository;

/** Thin transport around unmodified FedX; no XGAP plan selection or query rewrite. */
public final class FedXEndpoint {
    private static final int MAX_QUERY_BYTES = 1 << 20;
    private static final int MAX_RESULT_BYTES = 16 << 20;

    /** Diagnostic state only: do not change the exception or client response. */
    static final class FailureContext {
        String stage = "protocol";
        String callbackFailure;
        String querySha256 = "unavailable";

        void serialize(Runnable call) {
            String previous = stage;
            stage = "serialization";
            try { call.run(); }
            catch (RuntimeException error) { callbackFailure = stage; throw error; }
            finally { stage = previous; }
        }

        String diagnostic(Exception error) {
            Throwable root = error;
            int depth = 0;
            while (root.getCause() != null && root.getCause() != root && depth < 32) {
                root = root.getCause();
                depth++;
            }
            boolean bounded = root.getCause() != null && root.getCause() != root;
            return "FedX failure diagnostic: stage=" + (callbackFailure == null ? stage : callbackFailure)
                    + " exception_class=" + error.getClass().getName()
                    + " root_cause_class=" + (bounded ? "unavailable" : root.getClass().getName())
                    + " cause_depth_limit=" + bounded + " query_sha256=" + querySha256;
        }
    }

    /** The same JSON writer and callbacks; only annotate a thrown callback. */
    static final class DiagnosticWriter extends SPARQLResultsJSONWriter {
        private final FailureContext context;
        DiagnosticWriter(java.io.OutputStream output, FailureContext context) {
            super(output);
            this.context = context;
        }
        @Override public void startQueryResult(List<String> names) {
            context.serialize(() -> super.startQueryResult(names));
        }
        @Override public void handleSolution(BindingSet solution) {
            context.serialize(() -> super.handleSolution(solution));
        }
        @Override public void endQueryResult() {
            context.serialize(() -> super.endQueryResult());
        }
        @Override public void handleBoolean(boolean value) {
            context.serialize(() -> super.handleBoolean(value));
        }
        @Override public void handleLinks(List<String> links) {
            context.serialize(() -> super.handleLinks(links));
        }
    }

    private static String querySha256(String query) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                    .digest(query.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException error) {
            throw new IllegalStateException("Required SHA-256 unavailable", error);
        }
    }

    private static final class BoundedResult extends ByteArrayOutputStream {
        @Override public synchronized void write(int value) {
            if (count >= MAX_RESULT_BYTES) throw new IllegalStateException("Result byte limit exceeded");
            super.write(value);
        }
        @Override public synchronized void write(byte[] value, int offset, int length) {
            if (length > MAX_RESULT_BYTES - count) throw new IllegalStateException("Result byte limit exceeded");
            super.write(value, offset, length);
        }
    }

    private static void respond(HttpExchange exchange, int status, String type, byte[] body) throws IOException {
        exchange.getResponseHeaders().set("Content-Type", type);
        exchange.sendResponseHeaders(status, body.length);
        try (var out = exchange.getResponseBody()) { out.write(body); }
    }

    private static void query(HttpExchange exchange, Repository repository, int seconds) throws IOException {
        long started = System.nanoTime();
        FailureContext failure = new FailureContext();
        try {
            String method = exchange.getRequestMethod();
            if (!exchange.getRequestURI().getPath().equals("/sparql")
                    || !(method.equals("POST") || method.equals("GET"))) {
                respond(exchange, 405, "text/plain", "Use GET or POST /sparql".getBytes(StandardCharsets.UTF_8));
                return;
            }
            byte[] body;
            boolean encoded;
            if (method.equals("GET")) {
                String parameters = exchange.getRequestURI().getRawQuery();
                body = (parameters == null ? "" : parameters).getBytes(StandardCharsets.UTF_8);
                encoded = true;
            } else {
                String type = exchange.getRequestHeaders().getFirst("Content-Type");
                type = type == null ? "" : type.split(";", 2)[0].trim();
                encoded = type.equalsIgnoreCase("application/x-www-form-urlencoded");
                if (!encoded && !type.equalsIgnoreCase("application/sparql-query")) {
                    respond(exchange, 415, "text/plain", "Unsupported query media type".getBytes(StandardCharsets.UTF_8));
                    return;
                }
                try (var in = exchange.getRequestBody()) { body = in.readNBytes(MAX_QUERY_BYTES + 1); }
            }
            if (body.length > MAX_QUERY_BYTES) {
                respond(exchange, 413, "text/plain", "Query byte limit exceeded".getBytes(StandardCharsets.UTF_8));
                return;
            }
            BoundedResult answer = new BoundedResult();
            String text = new String(body, StandardCharsets.UTF_8);
            if (encoded) {
                // Decode only the HTTP envelope. Do not rewrite the author's
                // SPARQL, inject constraints, or replace unsupported algebra.
                String queryText = null;
                for (String part : text.split("&")) {
                    String[] pair = part.split("=", 2);
                    String name = URLDecoder.decode(pair[0], StandardCharsets.UTF_8);
                    if (name.equals("query") && pair.length == 2 && queryText == null)
                        queryText = URLDecoder.decode(pair[1], StandardCharsets.UTF_8);
                    else if (!name.equals("format"))
                        throw new IllegalArgumentException("Unsupported or duplicate protocol parameter");
                }
                if (queryText == null) throw new IllegalArgumentException("Missing query parameter");
                text = queryText;
            }
            failure.querySha256 = querySha256(text);
            failure.stage = "connection";
            try (var connection = repository.getConnection()) {
                // Tuple-query admission rejects UPDATE, ASK and graph construction.
                // Engine selection, source discovery and joins remain entirely FedX's.
                failure.stage = "prepare";
                var tuple = connection.prepareTupleQuery(QueryLanguage.SPARQL, text);
                failure.stage = "configure";
                tuple.setMaxExecutionTime(seconds);
                failure.stage = "serialization";
                var writer = new DiagnosticWriter(answer, failure);
                failure.stage = "evaluate";
                tuple.evaluate(writer);
                failure.stage = "connection_close";
            }
            failure.stage = "http_response";
            exchange.getResponseHeaders().set("X-XGAP-Adapter-Millis", Double.toString((System.nanoTime() - started) / 1e6));
            respond(exchange, 200, "application/sparql-results+json", answer.toByteArray());
        } catch (Exception error) {
            // Never retry, emit partial successful JSON, or turn an error into empty rows.
            System.err.println("FedX request failed: " + error.getClass().getSimpleName());
            // No exception message, query text, HTTP headers, response or secret.
            // Full stack traces can include those fields, even behind a flag.
            System.err.println(failure.diagnostic(error));
            respond(exchange, 500, "text/plain", ("FedX failure: " + error.getClass().getSimpleName()).getBytes(StandardCharsets.UTF_8));
        } finally {
            exchange.close();
        }
    }

    public static void main(String[] args) throws Exception {
        if (args.length == 1 && args[0].equals("--help")) {
            System.out.println("FedX 5.1.2 adapter: <loopback-port> <query-timeout-seconds> <endpoint> [endpoint ...]");
            System.out.println("Read-only SELECT via GET or POST /sparql; no dataset loading, fitting or retry.");
            return;
        }
        if (args.length < 3 || args.length > 66) throw new IllegalArgumentException("Expected port, timeout and 1..64 endpoints");
        int port = Integer.parseInt(args[0]), seconds = Integer.parseInt(args[1]);
        if (port < 1 || port > 65535 || seconds < 1 || seconds > 120) throw new IllegalArgumentException("Invalid port/timeout");
        // Match the published FedUP executor's batching/workers; preserve FedX
        // source selection and joins. The shared outer deadline is still required.
        var config = new FedXConfig()
                .withBoundJoinBlockSize(10).withJoinWorkerThreads(10)
                .withUnionWorkerThreads(10).withDebugQueryPlan(false);
        // Explicit compatibility switch for the pinned version's NULL failure
        // in QueryStringUtil.selectQueryStringBoundJoinVALUES on OPTIONAL rows.
        // Retain the engine's own ordinary left join; no query/answer rewriting.
        if (Boolean.getBoolean("xgap.fedx.disableOptionalBind")) config.withEnableOptionalAsBindJoin(false);
        var factory = FedXFactory.newFederation().withConfig(config);
        for (int i = 2; i < args.length; i++) {
            URI endpoint = URI.create(args[i]);
            if (!("http".equals(endpoint.getScheme()) || "https".equals(endpoint.getScheme()))
                    || endpoint.getHost() == null || endpoint.getUserInfo() != null || endpoint.getFragment() != null)
                throw new IllegalArgumentException("Expected explicit HTTP(S) endpoint without inline credentials");
            factory.withSparqlEndpoint(args[i]);
        }
        // A bundled jar can lose service-provider registrations; FedUP explicitly
        // registers these same result readers in its standalone executor.
        TupleQueryResultParserRegistry.getInstance().add(new SPARQLResultsXMLParserFactory());
        TupleQueryResultParserRegistry.getInstance().add(new SPARQLResultsJSONParserFactory());
        Repository repository = factory.create();
        var executor = Executors.newSingleThreadExecutor();
        HttpServer server = null;
        try {
            server = HttpServer.create(new InetSocketAddress("127.0.0.1", port), 0);
            server.createContext("/sparql", exchange -> query(exchange, repository, seconds));
            server.setExecutor(executor);
            HttpServer running = server;
            Runtime.getRuntime().addShutdownHook(new Thread(() -> {
                running.stop(0);
                executor.shutdownNow();
                repository.shutDown();
            }));
            server.start();
            System.err.println("FedX adapter ready on 127.0.0.1:" + port + "; members=" + (args.length - 2));
        } catch (Exception error) {
            if (server != null) server.stop(0);
            executor.shutdownNow();
            repository.shutDown();
            throw error;
        }
    }
}
