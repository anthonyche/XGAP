package org.xgap.experiments;

import com.sun.net.httpserver.*;
import java.io.*;
import java.lang.reflect.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;
import org.eclipse.rdf4j.query.*;
import org.eclipse.rdf4j.query.parser.sparql.SPARQLParser;
import org.eclipse.rdf4j.repository.*;

/** No listener, repository initialization, network, or source query execution. */
public final class FedXFailureDiagnosticCheck {
    static void require(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }
    static final class Exchange extends HttpExchange {
        final Headers request = new Headers(), response = new Headers();
        final ByteArrayOutputStream out = new ByteArrayOutputStream();
        final URI uri;
        int status;
        Exchange(String query) {
            uri = URI.create("http://localhost/sparql?query=" + URLEncoder.encode(query, StandardCharsets.UTF_8));
        }
        public Headers getRequestHeaders() { return request; }
        public Headers getResponseHeaders() { return response; }
        public URI getRequestURI() { return uri; }
        public String getRequestMethod() { return "GET"; }
        public HttpContext getHttpContext() { return null; }
        public void close() {}
        public InputStream getRequestBody() { return new ByteArrayInputStream(new byte[0]); }
        public OutputStream getResponseBody() { return out; }
        public void sendResponseHeaders(int code, long length) { status = code; }
        public InetSocketAddress getRemoteAddress() { return null; }
        public int getResponseCode() { return status; }
        public InetSocketAddress getLocalAddress() { return null; }
        public String getProtocol() { return "HTTP/1.1"; }
        public Object getAttribute(String key) { return null; }
        public void setAttribute(String key, Object value) {}
        public void setStreams(InputStream input, OutputStream output) {}
        public HttpPrincipal getPrincipal() { return null; }
    }
    static Object proxy(Class<?> type, InvocationHandler handler) {
        return java.lang.reflect.Proxy.newProxyInstance(type.getClassLoader(), new Class<?>[] {type}, handler);
    }
    static void checkRequest(String query, boolean failEvaluation) throws Exception {
        int[] evaluations = {0};
        String[] received = {null};
        TupleQuery tuple = (TupleQuery) proxy(TupleQuery.class, (p, method, args) -> {
            if (method.getName().equals("evaluate")) {
                evaluations[0]++;
                // Model an engine-internal malformed subquery, without evaluating one.
                throw new QueryEvaluationException(new MalformedQueryException("sensitive error text"));
            }
            if (method.getName().equals("setMaxExecutionTime")) return null;
            throw new AssertionError(method.getName());
        });
        RepositoryConnection connection = (RepositoryConnection) proxy(RepositoryConnection.class, (p, method, args) -> {
            if (method.getName().equals("prepareTupleQuery")) {
                received[0] = (String) args[1];
                new SPARQLParser().parseQuery(received[0], null);
                return tuple;
            }
            if (method.getName().equals("close")) return null;
            throw new AssertionError(method.getName());
        });
        Repository repository = (Repository) proxy(Repository.class, (p, method, args) -> {
            if (method.getName().equals("getConnection")) return connection;
            throw new AssertionError(method.getName());
        });
        Exchange exchange = new Exchange(query);
        var handler = FedXEndpoint.class.getDeclaredMethod("query", HttpExchange.class, Repository.class, int.class);
        handler.setAccessible(true);
        var log = new ByteArrayOutputStream();
        PrintStream original = System.err;
        try {
            System.setErr(new PrintStream(log, true, StandardCharsets.UTF_8));
            handler.invoke(null, exchange, repository, 20);
        } finally { System.setErr(original); }
        String diagnostic = log.toString(StandardCharsets.UTF_8);
        String outer = failEvaluation ? "QueryEvaluationException" : "MalformedQueryException";
        require(exchange.status == 500, "HTTP status unchanged");
        require(exchange.out.toString(StandardCharsets.UTF_8).equals("FedX failure: " + outer), "HTTP body unchanged");
        require(exchange.response.getFirst("Content-Type").equals("text/plain"), "media type unchanged");
        require(query.equals(received[0]), "decoded public query must be byte-identical");
        require(evaluations[0] == (failEvaluation ? 1 : 0), "parser failure must precede evaluate");
        require(diagnostic.contains("stage=" + (failEvaluation ? "evaluate" : "prepare") + " "), "actual stage");
        require(diagnostic.contains("exception_class=org.eclipse.rdf4j.query." + outer), "outer class");
        require(diagnostic.contains("root_cause_class="), "root cause class recorded");
        String sha = HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(query.getBytes(StandardCharsets.UTF_8)));
        require(diagnostic.contains("query_sha256=" + sha), "exact query digest");
        require(!diagnostic.contains("sensitive error text") && !diagnostic.contains("secret+%&"), "no diagnostic payload leak");
    }
    static void checkSerialization() {
        var context = new FedXEndpoint.FailureContext();
        context.stage = "evaluate";
        var writer = new FedXEndpoint.DiagnosticWriter(new OutputStream() {
            public void write(int value) throws IOException { throw new IOException("sensitive output text"); }
        }, context);
        try {
            writer.startQueryResult(List.of("s"));
            writer.endQueryResult();
            throw new AssertionError("writer must fail");
        } catch (RuntimeException error) {
            String diagnostic = context.diagnostic(error);
            require(diagnostic.contains("stage=serialization "), "writer callback stage");
            require(diagnostic.contains("root_cause_class=java.io.IOException"), "serialization root cause");
            require(!diagnostic.contains("sensitive output text"), "no output error payload");
        }
    }
    public static void main(String[] args) throws Exception {
        checkRequest("SELECT ?s WHERE { ?s ?p \"secret+%&中文\" } ORDER BY ?s DESC", false);
        checkRequest("SELECT ?s WHERE { ?s ?p \"secret+%&中文\" }", true);
        checkSerialization();
        System.out.println("prepare/evaluate/serialization diagnostics passed; source query executions=0");
    }
}
