// Focused storage regression: independent integer oracle and a real TDB MVCC reader.
import java.nio.ByteBuffer;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;
import java.lang.reflect.Field;
import org.apache.jena.dboe.base.block.*;
import org.apache.jena.dboe.base.page.PageBlockMgr;
import org.apache.jena.dboe.base.record.Record;
import org.apache.jena.dboe.trans.bplustree.*;
import org.apache.jena.query.*;
import org.apache.jena.rdf.model.*;
import org.apache.jena.tdb2.TDB2Factory;

public class XgapRangeCheck {
    static void require(boolean b,String message) { if(!b)throw new AssertionError(message); }
    static Record key(int n) { return new Record(ByteBuffer.allocate(4).putInt(n).array(),null); }
    static int number(Record r) { return ByteBuffer.wrap(r.getKey()).getInt(); }
    static class Reads extends BlockMgrWrapper {
        int reads;
        Reads(BlockMgr mgr) { super(mgr); }
        public Block getRead(long id) { reads++;return super.getRead(id); }
    }
    static Reads count(PageBlockMgr<?> mgr) throws Exception {
        Reads r=new Reads(mgr.getBlockMgr());
        Field f=PageBlockMgr.class.getDeclaredField("blockMgr");f.setAccessible(true);f.set(mgr,r);return r;
    }
    static void bounds(BPlusTree tree,List<Integer> oracle,Integer lo,Integer hi) {
        Iterator<Record> it=tree.iterator(lo==null?null:key(lo),hi==null?null:key(hi));
        List<Integer> got=new ArrayList<>();
        while(it.hasNext()) { require(it.hasNext(),"hasNext not idempotent");got.add(number(it.next())); }
        List<Integer> expected=oracle.stream().filter(v->(lo==null||v>=lo)&&(hi==null||v<hi)).toList();
        require(got.equals(expected),"range mismatch "+lo+".."+hi);
        try { it.next();throw new AssertionError("past-end next accepted"); }
        catch(NoSuchElementException expectedEnd) {}
    }
    static int ranges() throws Exception {
        BPlusTree tree=BPlusTreeFactory.makeMem(8,4,0);
        tree.nonTransactional();
        List<Integer> oracle=new ArrayList<>();for(int i=0;i<4096;i++)oracle.add(i*2);
        List<Integer> shuffled=new ArrayList<>(oracle);Collections.shuffle(shuffled,new Random(913));
        for(int n:shuffled)tree.insert(key(n));
        Reads records=count(tree.getRecordsMgr());
        Iterator<Record> prefix=tree.iterator();
        require(prefix.hasNext()&&number(prefix.next())==0,"first prefix record");
        int prefixReads=records.reads;
        if(prefix instanceof AutoCloseable closeable)closeable.close();
        bounds(tree,oracle,null,null);bounds(tree,oracle,null,1);bounds(tree,oracle,8190,null);
        bounds(tree,oracle,9999,null);bounds(tree,oracle,4,4);bounds(tree,oracle,9,3);
        Random rng=new Random(717);
        for(int i=0;i<100;i++) { int lo=rng.nextInt(8300);bounds(tree,oracle,lo,lo+rng.nextInt(500)); }
        for(int n=0;n<8192;n+=14) { tree.delete(key(n));oracle.remove(Integer.valueOf(n)); }
        bounds(tree,oracle,null,null);bounds(tree,oracle,511,8191);tree.close();
        return prefixReads;
    }
    static int query(Dataset d) {
        try(QueryExecution q=QueryExecutionFactory.create("SELECT ?s WHERE { ?s <urn:p> <urn:o> }",d)) {
            int n=0;ResultSet r=q.execSelect();while(r.hasNext()) { r.next();n++; }return n;
        }
    }
    static void mvcc(Path root) throws Exception {
        require(!Files.exists(root),"new TDB root required");
        Dataset d=TDB2Factory.connectDataset(root.toString());
        d.begin(ReadWrite.WRITE);
        Model m=d.getDefaultModel();Property p=m.createProperty("urn:p");Resource o=m.createResource("urn:o");
        for(int i=0;i<4096;i++)m.add(m.createResource("urn:s:"+i),p,o);
        d.commit();d.end();
        d.begin(ReadWrite.READ);
        try(QueryExecution q=QueryExecutionFactory.create("SELECT ?s WHERE { ?s <urn:p> <urn:o> }",d)) {
            ResultSet r=q.execSelect();require(r.hasNext(),"snapshot empty");Set<String> seen=new HashSet<>();
            seen.add(r.next().getResource("s").getURI());
            ExecutorService pool=Executors.newSingleThreadExecutor();
            try {
                pool.submit(()->{
                    d.begin(ReadWrite.WRITE);
                    try { Model w=d.getDefaultModel();w.removeAll();w.add(w.createResource("urn:new"),p,o);d.commit(); }
                    finally { d.end(); }
                }).get(15,TimeUnit.SECONDS);
            } finally { pool.shutdownNow(); }
            while(r.hasNext())seen.add(r.next().getResource("s").getURI());
            require(seen.size()==4096&&!seen.contains("urn:new"),"reader lost snapshot across page boundary");
        } finally { d.end(); }
        d.begin(ReadWrite.READ);try { require(query(d)==1,"new snapshot did not see commit"); }finally { d.end(); }
        d.begin(ReadWrite.WRITE);d.getDefaultModel().removeAll();d.abort();d.end();
        d.close();Dataset reopened=TDB2Factory.connectDataset(root.toString());
        reopened.begin(ReadWrite.READ);
        try { require(query(reopened)==1,"rollback/reopen changed result"); }
        finally { reopened.end();reopened.close(); }
    }
    public static void main(String[] args) throws Exception {
        XgapStorageMode.configure("direct");
        int reads=ranges();mvcc(Path.of(args[0]));
        System.out.println("{\"success\":true,\"range_cases\":108,\"first_record_page_gets\":"+reads+",\"mvcc_and_reopen\":true}");
    }
}
