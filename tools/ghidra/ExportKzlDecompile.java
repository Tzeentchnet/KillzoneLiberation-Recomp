// Export selected function decompilations to an ignored local file.
// @category KZL

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;

import java.io.PrintWriter;
import java.nio.charset.StandardCharsets;

public class ExportKzlDecompile extends GhidraScript {
    @Override
    protected void run() throws Exception {
        String[] arguments = getScriptArgs();
        if (arguments.length < 2) {
            throw new IllegalArgumentException(
                "expected output path and one or more addresses");
        }
        DecompInterface decompiler = new DecompInterface();
        decompiler.openProgram(currentProgram);
        try (PrintWriter out = new PrintWriter(
                arguments[0], StandardCharsets.UTF_8)) {
            for (int index = 1; index < arguments.length; index++) {
                Address address = toAddr(Long.decode(arguments[index]));
                Function function = getFunctionAt(address);
                if (function == null) {
                    throw new IllegalArgumentException(
                        "no function at " + address);
                }
                DecompileResults result =
                    decompiler.decompileFunction(function, 120, monitor);
                if (!result.decompileCompleted()) {
                    throw new IllegalStateException(
                        "decompile failed at " + address + ": " +
                        result.getErrorMessage());
                }
                out.println(
                    "/* " + address + " " + function.getName() + " */");
                out.println(
                    result.getDecompiledFunction().getC());
            }
        } finally {
            decompiler.dispose();
        }
        println("Exported decompilations: " + (arguments.length - 1));
    }
}
