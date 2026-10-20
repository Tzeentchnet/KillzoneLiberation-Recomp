// Apply the CSV emitted by tools/kzl/ghidra_symbols.py.
// @category KZL

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.SourceType;

import java.io.BufferedReader;
import java.io.FileReader;

public class ApplyKzlSymbols extends GhidraScript {
    @Override
    protected void run() throws Exception {
        String[] arguments = getScriptArgs();
        if (arguments.length != 1) {
            throw new IllegalArgumentException("expected one symbol CSV path");
        }
        int applied = 0;
        try (BufferedReader reader = new BufferedReader(new FileReader(arguments[0]))) {
            String line;
            boolean header = true;
            while ((line = reader.readLine()) != null) {
                if (header) {
                    header = false;
                    continue;
                }
                if (line.isBlank()) {
                    continue;
                }
                String[] fields = line.split(",", 3);
                if (fields.length != 3) {
                    throw new IllegalArgumentException("malformed CSV line: " + line);
                }
                Address address = toAddr(Long.decode(fields[0]));
                if (fields[2].startsWith("vtable:")) {
                    createLabel(address, fields[1], true, SourceType.USER_DEFINED);
                    setPlateComment(address, fields[2]);
                    applied++;
                    continue;
                }
                Function function = getFunctionAt(address);
                if (function == null) {
                    disassemble(address);
                    function = createFunction(address, fields[1]);
                } else {
                    function.setName(fields[1], SourceType.USER_DEFINED);
                }
                if (function == null) {
                    throw new IllegalStateException("cannot create function at " + address);
                }
                setPlateComment(address, fields[2]);
                applied++;
            }
        }
        println("Applied KZL symbols: " + applied);
    }
}
