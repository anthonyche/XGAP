package org.xgap.experiments;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.Executors;
import org.eclipse.rdf4j.federated.FedXConfig;
import org.eclipse.rdf4j.federated.FedXFactory;
import org.eclipse.rdf4j.query.QueryLanguage;
import org.eclipse.rdf4j.query.resultio.TupleQueryResultParserRegistry;
import org.eclipse.rdf4j.query.resultio.sparqljson.SPARQLResultsJSONParserFactory;
import org.eclipse.rdf4j.query.resultio.sparqljson.SPARQLResultsJSONWriter;
import org.eclipse.rdf4j.query.resultio.sparqlxml.SPARQLResultsXMLParserFactory;
import org.eclipse.rdf4j.repository.Repository;

/** Thin transport around unmodified FedX; no XGAP plan selection or query rewrite. */
public final class FedXEndpoint {
    private static final int MAX_QUERY_BYTES = 1 << 20;
    private static final int MAX_RESULT_BYTES = 16 << 20;

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
        try {
            if (!exchange.getRequestURI().getPath().equals("/sparql")
                    || !exchange.getRequestMethod().equals("POST")) {
                respond(exchange, 405, "text/plain", "Use POST /sparql".getBytes(StandardCharsets.UTF_8));
                return;
            }
            String type = exchange.getRequestHeaders().getFirst("Content-Type");
            if (type == null || !type.split(";", 2)[0].trim().equalsIgnoreCase("application/sparql-query")) {
                respond(exchange, 415, "text/plain", "Use application/sparql-query".getBytes(StandardCharsets.UTF_8));
                return;
            }
            byte[] body;
            try (var in = exchange.getRequestBody()) { body = in.readNBytes(MAX_QUERY_BYTES + 1); }
            if (body.length > MAX_QUERY_BYTES) {
                respond(exchange, 413, "text/plain", "Query byte limit exceeded".getBytes(StandardCharsets.UTF_8));
                return;
            }
            BoundedResult answer = new BoundedResult();
            try (var connection = repository.getConnection()) {
                // Tuple-query admission rejects UPDATE, ASK and graph construction.
                // Engine selection, source discovery and joins remain entirely FedX's.
                var tuple = connection.prepareTupleQuery(QueryLanguage.SPARQL, new String(body, StandardCharsets.UTF_8));
                tuple.setMaxExecutionTime(seconds);
                tuple.evaluate(new SPARQLResultsJSONWriter(answer));
            }
            exchange.getResponseHeaders().set("X-XGAP-Adapter-Millis", Double.toString((System.nanoTime() - started) / 1e6));
            respond(exchange, 200, "application/sparql-results+json", answer.toByteArray());
        } catch (Exception error) {
            // Never retry, emit partial successful JSON, or turn an error into empty rows.
            System.err.println("FedX request failed: " + error.getClass().getSimpleName());
            respond(exchange, 500, "text/plain", ("FedX failure: " + error.getClass().getSimpleName()).getBytes(StandardCharsets.UTF_8));
        } finally {
            exchange.close();
        }
    }

    public static void main(String[] args) throws Exception {
        if (args.length == 1 && args[0].equals("--help")) {
            System.out.println("FedX 5.1.2 adapter: <loopback-port> <query-timeout-seconds> <endpoint> [endpoint ...]");
            System.out.println("Read-only SELECT via POST /sparql; no dataset loading, fitting or retry.");
            return;
        }
        if (args.length < 3 || args.length > 66) throw new IllegalArgumentException("Expected port, timeout and 1..64 endpoints");
        int port = Integer.parseInt(args[0]), seconds = Integer.parseInt(args[1]);
        if (port < 1 || port > 65535 || seconds < 1 || seconds > 120) throw new IllegalArgumentException("Invalid port/timeout");
        // Match the published FedUP executor's batching/workers; preserve FedX
        // source selection and joins. The shared outer deadline is still required.
        var factory = FedXFactory.newFederation().withConfig(new FedXConfig()
                .withBoundJoinBlockSize(10).withJoinWorkerThreads(10)
                .withUnionWorkerThreads(10).withDebugQueryPlan(false));
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
