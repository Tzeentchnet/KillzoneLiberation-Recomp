// Export function-to-string references for library/class recovery.
// @category KZL

import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Data;
import ghidra.program.model.listing.DataIterator;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceIterator;

import java.io.PrintWriter;
import java.nio.charset.StandardCharsets;
import java.util.Base64;

public class ExportKzlStringXrefs extends GhidraScript {
    @Override
    protected void run() throws Exception {
        String[] arguments = getScriptArgs();
        if (arguments.length != 1) {
            throw new IllegalArgumentException("expected one TSV output path");
        }
        int count = 0;
        try (PrintWriter out = new PrintWriter(
                arguments[0], StandardCharsets.UTF_8)) {
            out.println("string_address\treference_address\tfunction_address\tvalue_base64");
            DataIterator data = currentProgram.getListing().getDefinedData(true);
            while (data.hasNext()) {
                Data item = data.next();
                Object value = item.getValue();
                if (!(value instanceof String)) {
                    continue;
                }
                String text = (String)value;
                ReferenceIterator references =
                    currentProgram.getReferenceManager().getReferencesTo(item.getAddress());
                while (references.hasNext()) {
                    Reference reference = references.next();
                    Function function = getFunctionContaining(reference.getFromAddress());
                    if (function == null) {
                        continue;
                    }
                    String encoded = Base64.getEncoder().encodeToString(
                        text.getBytes(StandardCharsets.UTF_8));
                    out.printf(
                        "%s\t%s\t%s\t%s%n",
                        item.getAddress(),
                        reference.getFromAddress(),
                        function.getEntryPoint(),
                        encoded);
                    count++;
                }
            }
        }
        println("Exported KZL string xrefs: " + count);
    }
}
