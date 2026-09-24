// Offline, pinned Jena 5.6.0 diagnostic. Never installed in the online planner.
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import java.util.function.Consumer;
import com.google.gson.GsonBuilder;
import org.apache.jena.atlas.iterator.IteratorWrapper;
import org.apache.jena.atlas.lib.tuple.Tuple;
import org.apache.jena.query.*;
import org.apache.jena.tdb2.TDB2Factory;
import org.apache.jena.tdb2.sys.TDBInternal;
import org.apache.jena.tdb2.store.*;
import org.apache.jena.tdb2.store.tupletable.*;

public class XgapTdbReplay {
    static final Map<String,Counts> counts = new ConcurrentHashMap<>();
    static final Thread queryThread = Thread.currentThread();
    static volatile String phase = "open", operation = "none";
    static volatile long operationAt = System.nanoTime(), queryAt;
    static volatile long rows;
    static String fileMode;
    static String rangeImplementation;
    static final Map<String,List<String>> blockManagers=new ConcurrentHashMap<>();
    static Path metrics;
    static Map<String,Long> baseline;
    static class Counts {
        AtomicLong lookups=new AtomicLong(), tuples=new AtomicLong(), nanos=new AtomicLong();
        Map<String,Long> snapshot() { return Map.of("find_calls",lookups.get(),"tuple_yields",tuples.get(),"index_api_ns",nanos.get()); }
    }
    static class CountIndex extends TupleIndexWrapper {
        CountIndex(TupleIndex index) { super(index); }
        public Iterator<Tuple<NodeId>> find(Tuple<NodeId> pattern) {
            StringBuilder mask=new StringBuilder();
            for (NodeId id:pattern) mask.append(NodeId.isAny(id)?'?':'B');
            String key=getName()+":"+mask;
            Counts c=counts.computeIfAbsent(key,k->new Counts());
            c.lookups.incrementAndGet();
            long start=System.nanoTime();operation=key+":find";operationAt=start;
            Iterator<Tuple<NodeId>> iterator;
            try { iterator=super.find(pattern); }
            finally { c.nanos.addAndGet(System.nanoTime()-start); operation="outside-index"; }
            return new IteratorWrapper<Tuple<NodeId>>(iterator) {
                public boolean hasNext() {
                    long at=System.nanoTime();operation=key+":hasNext";operationAt=at;
                    try { return super.hasNext(); }
                    finally { c.nanos.addAndGet(System.nanoTime()-at); operation="outside-index"; }
                }
                public Tuple<NodeId> next() {
                    long at=System.nanoTime();operation=key+":next";operationAt=at;
                    try { Tuple<NodeId> t=super.next();c.tuples.incrementAndGet();return t; }
                    finally { c.nanos.addAndGet(System.nanoTime()-at); operation="outside-index"; }
                }
                public void forEachRemaining(Consumer<? super Tuple<NodeId>> consumer) {
                    while(hasNext()) consumer.accept(next());
                }
            };
        }
    }
    static void install(TupleTable table) {
        for(int i=0;i<table.numIndexes();i++) {
            TupleIndex index=table.getIndex(i);
            if(index!=null) {
                TupleIndex base=index.baseTupleIndex();
                if(base instanceof TupleIndexRecord record && record.getRangeIndex() instanceof org.apache.jena.dboe.trans.bplustree.BPlusTree tree) {
                    List<String> chain=new ArrayList<>();
                    org.apache.jena.dboe.base.block.BlockMgr mgr=tree.getRecordsMgr().getBlockMgr();
                    for(int depth=0;depth<16;depth++) {
                        chain.add(mgr.getClass().getName()+" "+mgr.toString());
                        if(mgr instanceof org.apache.jena.dboe.base.block.BlockMgrWrapper wrap)mgr=wrap.getWrapped();else break;
                    }
                    blockManagers.put(index.getName(),chain);
                }
                table.setTupleIndex(i,new CountIndex(index));
            }
        }
    }
    static String read(String name) {
        try { return Files.readString(Path.of(name)).trim(); }
        catch(Exception e) { return null; }
    }
    static Map<String,Long> proc() {
        Map<String,Long> out=new TreeMap<>();
        String stat=read("/proc/self/stat");
        if(stat!=null) {
            String[] s=stat.substring(stat.lastIndexOf(')')+2).split("\\s+");
            out.put("minor_faults",Long.parseLong(s[7]));out.put("major_faults",Long.parseLong(s[9]));
            out.put("user_ticks",Long.parseLong(s[11]));out.put("system_ticks",Long.parseLong(s[12]));
        }
        String io=read("/proc/self/io");
        if(io!=null) for(String line:io.split("\n")) {
            String[] v=line.split(":\\s*");out.put(v[0],Long.parseLong(v[1]));
        }
        return out;
    }
    static synchronized void snapshot() {
        try {
            Map<String,Object> out=new TreeMap<>();out.put("phase",phase);out.put("rows",rows);out.put("file_mode",fileMode);
            out.put("range_implementation",rangeImplementation);
            out.put("index_block_managers",blockManagers);out.put("dboe_file_mode",org.apache.jena.dboe.sys.SystemIndex.fileMode().toString());
            out.put("jena_version", org.apache.jena.Jena.VERSION);out.put("linux_proc_available",Files.exists(Path.of("/proc/self/stat")));
            out.put("query_elapsed_ms",queryAt==0?null:(System.nanoTime()-queryAt)/1e6);
            out.put("operation",operation);out.put("operation_age_ms",(System.nanoTime()-operationAt)/1e6);
            Map<String,Object> indexes=new TreeMap<>();counts.forEach((k,v)->indexes.put(k,v.snapshot()));out.put("indexes",indexes);
            Map<String,Long> p=proc();out.put("proc_cumulative",p);
            Map<String,Long> delta=new TreeMap<>();if(baseline!=null) p.forEach((k,v)->{if(baseline.containsKey(k)) delta.put(k,v-baseline.get(k));});
            out.put("query_proc_delta",baseline==null?null:delta);
            List<String> stack=new ArrayList<>();for(StackTraceElement e:queryThread.getStackTrace()) { if(stack.size()==18)break;stack.add(e.toString()); }
            out.put("query_thread_stack",stack);
            // Main-thread wchan is insufficient: Java's query thread is often another native TID.
            List<Map<String,String>> blocked=new ArrayList<>();
            try(var paths=Files.list(Path.of("/proc/self/task"))) {
                paths.limit(256).forEach(pth->{String s=read(pth+"/stat");if(s!=null&&s.substring(s.lastIndexOf(')')+2).startsWith("D ")) {
                    Map<String,String> b=new TreeMap<>();b.put("tid",pth.getFileName().toString());b.put("wchan",read(pth+"/wchan"));blocked.add(b);
                }});
            } catch(Exception ignored) {}
            out.put("sampled_uninterruptible_threads",blocked);
            out.put("delayacct_enabled",read("/proc/sys/kernel/task_delayacct"));
            out.put("measurement", "TupleIndex.find calls and tuples yielded, not all B-tree records/pages examined; process deltas include sampler. No cache flush; timing is diagnostic with instrumentation overhead. All-variable table scan cache not intercepted.");
            String json=new GsonBuilder().serializeNulls().create().toJson(out);
            Files.writeString(metrics.resolveSibling(metrics.getFileName()+".tmp"),json);
            Files.move(metrics.resolveSibling(metrics.getFileName()+".tmp"),metrics,StandardCopyOption.REPLACE_EXISTING,StandardCopyOption.ATOMIC_MOVE);
            Files.writeString(metrics.resolveSibling("samples.jsonl"),json+"\n",StandardOpenOption.CREATE,StandardOpenOption.APPEND);
        }catch(Exception e) { System.err.println("snapshot failed: "+e); }
    }
    public static void main(String[] args) throws Exception {
        if(args.length!=5 || !Set.of("mapped","direct").contains(args[4])) throw new IllegalArgumentException("store query metrics result-json mapped|direct");
        XgapStorageMode.configure(args[4]);
        Class<?> range=Class.forName("org.apache.jena.dboe.trans.bplustree.BPTreeRangeIterator");
        boolean lazy=Arrays.stream(range.getDeclaredMethods()).anyMatch(m->m.getName().equals("lazyPages"));
        rangeImplementation=(lazy?"xgap-experimental-lazy-v1 ":"jena-original ")+range.getProtectionDomain().getCodeSource().getLocation();
        fileMode=org.apache.jena.tdb2.sys.SystemTDB.fileMode().toString();
        if(!fileMode.equals(args[4]))throw new IllegalStateException("file mode not applied");
        metrics=Path.of(args[2]);if(Files.exists(metrics))throw new IllegalArgumentException("new output required");
        ScheduledExecutorService timer=Executors.newSingleThreadScheduledExecutor(r->{Thread t=new Thread(r,"xgap-diagnostic");t.setDaemon(true);return t;});
        timer.scheduleAtFixedRate(XgapTdbReplay::snapshot,0,1,TimeUnit.SECONDS);
        Dataset dataset=TDB2Factory.connectDataset(args[0]);
        DatasetGraphTDB tdb=TDBInternal.getDatasetGraphTDB(dataset);
        install(tdb.getTripleTable().getNodeTupleTable().getTupleTable());
        install(tdb.getQuadTable().getNodeTupleTable().getTupleTable());
        Query query=QueryFactory.read(args[1]);
        dataset.begin(ReadWrite.READ);
        baseline=proc();queryAt=System.nanoTime();phase="query";
        try(QueryExecution exec=QueryExecutionFactory.create(query,dataset)) {
            ResultSet rs=exec.execSelect();
            // The selected failed request is bounded to 567 rows; reject unexpected output explosion.
            List<Map<String,String>> results=new ArrayList<>();List<String> vars=rs.getResultVars();
            while(rs.hasNext()) {
                QuerySolution sol=rs.next();Map<String,String> row=new TreeMap<>();for(String var:vars)if(sol.contains(var))row.put(var,sol.get(var).toString());
                results.add(row);rows++;if(rows>1024)throw new IllegalStateException("diagnostic output bound");
            }
            Files.writeString(Path.of(args[3]),new GsonBuilder().create().toJson(results),StandardOpenOption.CREATE_NEW);
            phase="complete";
        } finally { snapshot();timer.shutdownNow();dataset.end();dataset.close(); }
    }
}
