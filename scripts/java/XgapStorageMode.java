// Jena 5.6 uses DBOE SystemIndex when creating B+tree block managers.
// TDB2's CLI context/SystemTDB alone does not select that lower-level mode.
import org.apache.jena.dboe.base.block.FileMode;
import org.apache.jena.dboe.sys.SystemIndex;
import org.apache.jena.tdb2.sys.SystemTDB;

public final class XgapStorageMode {
    public static void configure(String mode) {
        FileMode selected=FileMode.valueOf(mode);
        SystemIndex.setFileMode(selected);
        SystemTDB.setFileMode(selected);
        if(SystemIndex.fileMode()!=selected || SystemTDB.fileMode()!=selected)
            throw new IllegalStateException("Storage mode was initialized before configuration");
    }
    public static void main(String[] args) {
        if(args.length<1)throw new IllegalArgumentException("mapped|direct followed by Fuseki args");
        configure(args[0]);
        System.err.println("XGAP storage: TDB="+SystemTDB.fileMode()+" DBOE="+SystemIndex.fileMode());
        org.apache.jena.fuseki.main.cmds.FusekiServerCmd.main(java.util.Arrays.copyOfRange(args,1,args.length));
    }
}
