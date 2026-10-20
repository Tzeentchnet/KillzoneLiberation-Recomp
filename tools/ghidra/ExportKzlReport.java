// Export reproducible metadata from the analyzed KZL program.
// @category KZL

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;

import java.io.PrintWriter;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;

public class ExportKzlReport extends GhidraScript {
    @Override
    protected void run() throws Exception {
        String[] arguments = getScriptArgs();
        if (arguments.length != 1) {
            throw new IllegalArgumentException("expected one output path");
        }
        int functions = 0;
        int namedImports = 0;
        List<String> named = new ArrayList<>();
        FunctionIterator iterator = currentProgram.getFunctionManager().getFunctions(true);
        while (iterator.hasNext()) {
            Function function = iterator.next();
            functions++;
            Address entry = function.getEntryPoint();
            if (entry.getOffset() >= 0x08d8e000L &&
                entry.getOffset() < 0x08d90000L &&
                !function.getName().startsWith("FUN_")) {
                namedImports++;
            }
            if (!function.getName().startsWith("FUN_")) {
                named.add(entry + " " + function.getName());
            }
        }
        try (PrintWriter out = new PrintWriter(
                arguments[0], StandardCharsets.UTF_8)) {
            out.println("# KZL Ghidra analysis report");
            out.println("program=" + currentProgram.getName());
            out.println("format=" + currentProgram.getExecutableFormat());
            out.println("language=" + currentProgram.getLanguageID());
            out.println("compiler=" + currentProgram.getCompilerSpec().getCompilerSpecID());
            out.println("image_base=" + currentProgram.getImageBase());
            out.println("min_address=" + currentProgram.getMinAddress());
            out.println("max_address=" + currentProgram.getMaxAddress());
            out.println("functions=" + functions);
            out.println("named_import_stubs=" + namedImports);
            out.println("named_functions=" + named.size());
            for (String function : named) {
                out.println("function=" + function);
            }
        }
        println("Exported KZL report: " + arguments[0]);
    }
}
