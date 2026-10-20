// Export analyzed function boundaries for PPSSPP known-function matching.
// @category KZL

import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;

import java.io.PrintWriter;
import java.nio.charset.StandardCharsets;

public class ExportKzlFunctions extends GhidraScript {
    @Override
    protected void run() throws Exception {
        String[] arguments = getScriptArgs();
        if (arguments.length != 1) {
            throw new IllegalArgumentException("expected one CSV output path");
        }
        int count = 0;
        try (PrintWriter out = new PrintWriter(
                arguments[0], StandardCharsets.UTF_8)) {
            out.println("address,end,name");
            FunctionIterator iterator =
                currentProgram.getFunctionManager().getFunctions(true);
            while (iterator.hasNext()) {
                Function function = iterator.next();
                long address = function.getEntryPoint().getOffset();
                long end = function.getBody().getMaxAddress().getOffset();
                if (address >= 0x08804000L && address < 0x0A000000L) {
                    out.printf(
                        "0x%08x,0x%08x,%s%n",
                        address, end, function.getName());
                    count++;
                }
            }
        }
        println("Exported KZL functions: " + count);
    }
}
