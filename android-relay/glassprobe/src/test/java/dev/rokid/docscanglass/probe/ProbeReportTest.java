package dev.rokid.docscanglass.probe;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertThrows;
import static org.junit.Assert.assertTrue;

import java.util.Arrays;
import java.util.List;

import org.junit.Test;

public class ProbeReportTest {

    @Test
    public void startsWithEveryDeclaredProbePendingAndInDeclaredOrder() {
        ProbeReport report = new ProbeReport(Arrays.asList("P1 DISPLAY", "P2 CAMERA"));

        assertEquals(
                Arrays.asList("P1 DISPLAY PENDING", "P2 CAMERA PENDING"),
                report.lines());
    }

    @Test
    public void recordsAResultWithoutReorderingTheReport() {
        ProbeReport report =
                new ProbeReport(Arrays.asList("P1 DISPLAY", "P2 CAMERA", "P3 NETWORK"));

        report.record("P2 CAMERA", ProbeReport.Status.OK, "2 ids");

        assertEquals(
                Arrays.asList(
                        "P1 DISPLAY PENDING",
                        "P2 CAMERA OK 2 ids",
                        "P3 NETWORK PENDING"),
                report.lines());
    }

    @Test
    public void rejectsAnUndeclaredProbeKey() {
        ProbeReport report = new ProbeReport(Arrays.asList("P1 DISPLAY"));

        assertThrows(
                IllegalArgumentException.class,
                () -> report.record("P9 UNKNOWN", ProbeReport.Status.OK, "x"));
    }

    @Test
    public void keepsOnlyTheLatestResultForARepeatedKey() {
        ProbeReport report = new ProbeReport(Arrays.asList("P2 CAMERA"));

        report.record("P2 CAMERA", ProbeReport.Status.FAILED, "no permission");
        report.record("P2 CAMERA", ProbeReport.Status.OK, "captured");

        assertEquals(Arrays.asList("P2 CAMERA OK captured"), report.lines());
    }

    @Test
    public void boundsDetailLengthSoOneLineStaysReadableOnTheGlasses() {
        ProbeReport report = new ProbeReport(Arrays.asList("P3 NETWORK"));
        StringBuilder detail = new StringBuilder();
        for (int i = 0; i < 200; i++) {
            detail.append('x');
        }

        report.record("P3 NETWORK", ProbeReport.Status.FAILED, detail.toString());

        List<String> lines = report.lines();
        assertEquals(1, lines.size());
        assertEquals(
                "P3 NETWORK FAILED ".length() + ProbeReport.MAX_DETAIL_CHARS,
                lines.get(0).length());
        assertTrue(lines.get(0).endsWith("..."));
    }

    @Test
    public void rendersAResultWithoutDetailAsStatusOnly() {
        ProbeReport report = new ProbeReport(Arrays.asList("P4 BACK"));

        report.record("P4 BACK", ProbeReport.Status.OK, null);

        assertEquals(Arrays.asList("P4 BACK OK"), report.lines());
    }
}
